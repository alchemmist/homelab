import argparse
import concurrent.futures
import json
import subprocess
import tempfile
from pathlib import Path


ADDRESSES = ("109.173.40.247", "176.98.185.59")
HOSTS = (
    "alchemmist.xyz",
    "www.alchemmist.xyz",
    "cats.alchemmist.xyz",
    "fq.alchemmist.xyz",
    "img.alchemmist.xyz",
    "llm.alchemmist.xyz",
    "chat.alchemmist.xyz",
    "lms.alchemmist.xyz",
    "monori.alchemmist.xyz",
    "remark42.alchemmist.xyz",
    "socrat.alchemmist.xyz",
    "status.alchemmist.xyz",
    "umami.alchemmist.xyz",
    "wiki.socrat.alchemmist.xyz",
    "vpn.alchemmist.xyz",
)
PROBES = {
    "img.alchemmist.xyz": ("/", 301, None),
    "llm.alchemmist.xyz": ("/health/liveliness", 200, b"I'm alive!"),
    "remark42.alchemmist.xyz": ("/ping", 200, b"pong"),
    "status.alchemmist.xyz": ("/api/status-page/heartbeat/socrat", 200, b"heartbeatList"),
    "vpn.alchemmist.xyz": ("/", 404, None),
}


def check_endpoint(item):
    host, address = item
    path, expected, marker = PROBES.get(host, ("/", 200, None))
    with tempfile.TemporaryDirectory(prefix="public-ingress-check-") as directory:
        body = Path(directory) / "body"
        result = subprocess.run(
            [
                "curl", "--noproxy", "*", "--silent", "--show-error",
                "--connect-timeout", "5", "--max-time", "15",
                "--resolve", f"{host}:443:{address}",
                "--output", str(body), "--write-out", "%{http_code}",
                f"https://{host}{path}",
            ],
            capture_output=True, text=True, timeout=20,
        )
        code = result.stdout.strip()
        content = body.read_bytes() if body.exists() else b""
    valid = result.returncode == 0 and code == str(expected)
    if marker is not None:
        valid = valid and marker in content
    if host == "status.alchemmist.xyz" and valid:
        try:
            valid = isinstance(json.loads(content).get("heartbeatList"), dict)
        except (ValueError, AttributeError):
            valid = False
    tls = "verified" if result.returncode == 0 else "failed/unverified"
    detail = "ok" if valid else f"FAILED expected HTTP {expected}; curl={result.returncode}"
    print(f"{host:25} {address:15} HTTP {code or '000'} TLS {tls} {detail}", flush=True)
    return host, code, valid


def check_dns(host):
    result = subprocess.run(
        ["dig", "@ns1.reg.ru", host, "A", "+short", "+time=3", "+tries=1"],
        capture_output=True, text=True, timeout=10,
    )
    addresses = set(result.stdout.split())
    valid = result.returncode == 0 and addresses == set(ADDRESSES)
    print(f"DNS {host:25} {','.join(sorted(addresses)) or 'no answer'} {'ok' if valid else 'FAILED'}")
    return valid


def main():
    parser = argparse.ArgumentParser(description="Check both public HTTPS entrances without depending on DNS propagation.")
    parser.add_argument("--check-dns", action="store_true", help="Also require both A records on ns1.reg.ru.")
    args = parser.parse_args()
    endpoints = [(host, address) for host in HOSTS for address in ADDRESSES]
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(check_endpoint, endpoints))
        valid = all(item[2] for item in results)
        if args.check_dns:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                dns_results = list(executor.map(check_dns, HOSTS))
            valid = all(dns_results) and valid
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"FAILED: {type(error).__name__}: {error}")
        return 1
    print(f"HTTPS checks: {sum(item[2] for item in results)}/{len(results)} passed")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
