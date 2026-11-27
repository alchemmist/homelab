"""Bracket anonymous HTTPS route checks with independent public DNS reads.

This is an observer, not a DNS writer, a self-IP check or a VPN probe. Connect
only to the configured entrance addresses, never to a destination learned from
a DNS answer. Unknown IPv4/IPv6 evidence is reported without following it.
"""

import ipaddress
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import yaml

from ci.quality.public_dns_snapshot import observe, questions
from ci.quality.public_web import CATALOG, MONORI, eligible_sites

BLOG = "www.alchemmist.xyz"
VENICE = "venice.socrat.alchemmist.xyz"
PATHS = {BLOG: "/", VENICE: "/v1/models", MONORI: "/api/auth/me"}
DENIALS = {VENICE: "Missing bearer token", MONORI: "Not authenticated"}
LIMIT = 131072


def check(host, ip):
    url = f"https://{host}{PATHS[host]}"
    args = [
        "curl",
        "--disable",
        "--noproxy",
        "*",
        "--silent",
        "--proto",
        "=https",
        "--connect-timeout",
        "4",
        "--max-time",
        "7",
        "--max-filesize",
        str(LIMIT),
        "--resolve",
        f"{host}:443:{ip}",
        "--header",
        "Accept-Encoding: identity",
        "--write-out",
        "\\n%{response_code} %{content_type}",
        url,
    ]
    try:
        r = subprocess.run(args, capture_output=True, timeout=9, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "client-failed"
    if r.returncode:
        return {
            7: "connect-failed",
            28: "timeout",
            35: "tls-handshake-failed",
            60: "tls-verification-failed",
            63: "oversize",
        }.get(r.returncode, "transfer-failed")
    body, marker, metadata = r.stdout.rpartition(b"\n")
    code, _, ct = metadata.partition(b" ")
    mime = ct.partition(b";")[0].lower().strip()
    if not marker or len(body) > LIMIT:
        return "invalid-response"
    if (
        host == BLOG
        and code == b"200"
        and mime == b"text/html"
        and b"<title>Personal blog of Anton Grishin</title>" in body
    ):
        return "matched"
    if host in DENIALS and code == b"401" and mime == b"application/json":
        try:
            if json.loads(body) == {"detail": DENIALS[host]}:
                return "matched"
        except (ValueError, RecursionError):
            pass
    return "unexpected-application-response"


def verdict(before, after, routes):
    if before != after:
        return "dns-changed"
    if not isinstance(before, dict) or not before.get("A") or before.get("AAAA") != []:
        return "dns-incomplete-or-unsupported"
    if not all(address in routes for address in before["A"]):
        return "outside-reviewed-entrances"
    if any(routes[address] != "matched" for address in before["A"]):
        return "advertised-path-not-verified"
    return "advertised-paths-matched"


def route_peers(host, ips):
    # NL may answer authoritative DNS for Monori; it is not a permitted web destination.
    return tuple(ips[s] for s in eligible_sites(host))


def main():
    catalog = yaml.safe_load(CATALOG.read_text())
    ips = {s: str(ipaddress.IPv4Address(d["publicIP"])) for s, d in catalog["replicas"].items()}
    if (
        set(ips) != {"home", "nl", "moscow"}
        or len(set(ips.values())) != 3
        or not set(PATHS) <= set(questions(catalog))
    ):
        raise ValueError("unreviewed inventory")
    with ThreadPoolExecutor(3) as pool:

        def dns():
            return dict(pool.map(lambda s: observe(s, ips[s], list(PATHS)), ips))

        before = dns()
        routes = {
            h: dict(zip(peers, pool.map(lambda ip: check(h, ip), peers), strict=True))
            for h in PATHS
            for peers in [route_peers(h, ips)]
        }
        after = dns()
    cases = {
        s: {
            h + "/" + t: verdict(before[s][h + "/" + t], after[s][h + "/" + t], routes[h])
            for h in PATHS
            for t in ("udp", "tcp")
        }
        for s in ips
    }
    print(
        json.dumps(
            {"before": before, "https": routes, "after": after, "cases": cases}, sort_keys=True
        )
    )
    return int(
        any(outcome != "advertised-paths-matched" for r in cases.values() for outcome in r.values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
