"""Anonymous fixed-path password route witness; never follow or print Location."""

import ipaddress
import json
import subprocess

import yaml

from ci.quality.public_web import CATALOG

HOST = "auth.socrat.alchemmist.xyz"
ROOT = "/change-password"
PATHS = (ROOT + "/", ROOT)
EXPECTED = {
    ROOT + "/": "https://" + HOST + ROOT,
    ROOT: "https://" + HOST + "/if/flow/default-authentication-flow/?next=%2Fchange-password",
}


def sample(path, *, ip=None, local_port=None):
    if path not in EXPECTED or (ip is None) == (local_port is None):
        raise ValueError("invalid probe target")
    if ip is not None:
        args = ["--proto", "=https", "--resolve", f"{HOST}:443:{ipaddress.IPv4Address(ip)}"]
        url = "https://" + HOST + path
    else:
        if type(local_port) is not int or not 1024 <= local_port <= 65535:
            raise ValueError("invalid loopback port")
        args = ["--proto", "=http", "--header", "Host: " + HOST]
        url = f"http://127.0.0.1:{local_port}" + path
    try:
        r = subprocess.run(
            [
                "curl",
                "--disable",
                "--noproxy",
                "*",
                "--silent",
                "--max-time",
                "7",
                "--max-filesize",
                "8192",
                "--output",
                "/dev/null",
                "--write-out",
                "%{response_code}\\n%header{location}",
                *args,
                url,
            ],
            capture_output=True,
            timeout=9,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "client-failed"
    if r.returncode:
        return "transfer-unverified"
    status, sep, location = r.stdout.partition(b"\n")
    if not sep or b"\n" in location or b"\r" in location:
        return "unexpected-response"
    if status == b"302" and location == EXPECTED[path].encode():
        return "matched"
    if status == b"502":
        return "http-502"
    return "unexpected-response"


def main():
    try:
        sites = yaml.safe_load(CATALOG.read_text())["replicas"]
        if not isinstance(sites, dict) or set(sites) != {"home", "nl", "moscow"}:
            raise ValueError
        ips = {
            s: str(ipaddress.IPv4Address(d["publicIP"]))
            for s, d in sites.items()
            if isinstance(d, dict) and isinstance(d.get("publicIP"), str)
        }
        if len(set(ips.values())) != 3:
            raise ValueError
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError):
        print(json.dumps({"error": "invalid-entrance-inventory"}))
        return 1
    results = {s: {path: sample(path, ip=ip) for path in PATHS} for s, ip in ips.items()}
    print(json.dumps(results, sort_keys=True))
    return int(any(v != "matched" for row in results.values() for v in row.values()))


if __name__ == "__main__":
    raise SystemExit(main())
