"""Bracket anonymous HTTPS route checks with independent public DNS reads.

This is an observer, not a DNS writer, a geographic outage test or a VPN probe. Connect
only to the configured entrance addresses, never to a destination learned from
a DNS answer. Unknown IPv4/IPv6 evidence is reported without following it.
"""

import ipaddress
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

import yaml

from ci.quality.public_dns_snapshot import observe, questions
from ci.quality.public_web import CATALOG

BLOG = "www.alchemmist.xyz"
VENICE = "venice.socrat.alchemmist.xyz"
MONORI = "monori.alchemmist.xyz"
WIKI = "wiki.socrat.alchemmist.xyz"
ARGO = "argocd.socrat.alchemmist.xyz"
HARBOR = "harbor.socrat.alchemmist.xyz"
PATHS = {
    BLOG: "/",
    VENICE: "/v1/models",
    MONORI: "/api/auth/me",
    WIKI: "/api/auth/me",
    ARGO: "/api/v1/applications",
    HARBOR: "/v2/",
}
ADDITIONAL = {ARGO: ("/api/version",), HARBOR: ("/v2", "/api/v2.0/ping")}
CHALLENGE = (
    b'Bearer realm="https://harbor.socrat.alchemmist.xyz/service/token",service="harbor-registry"'
)
DENIALS = {VENICE: "Missing bearer token", MONORI: "Not authenticated"}
LIMIT = 131072


def unique_fields(pairs):
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError("ambiguous JSON fields")
    return data


def check(host, ip):
    for path in (PATHS[host], *ADDITIONAL.get(host, ())):
        outcome = _path(host, ip, path)
        if outcome != "matched":
            return outcome
    return "matched"


def _path(host, ip, path):
    url = f"https://{host}{path}"
    registry = host == HARBOR and path == "/v2/"
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
        "\\n%{response_code} %{content_type}"
        + ("\\n%header{www-authenticate}" if registry else ""),
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
    output = r.stdout
    if registry:
        output, sep, challenge = output.rpartition(b"\n")
        if not sep or challenge != CHALLENGE:
            return "unexpected-registry-challenge"
    body, marker, metadata = output.rpartition(b"\n")
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
    if host == HARBOR and code == b"200":
        if path == "/v2" and mime == b"text/html" and b"<title>Harbor</title>" in body:
            return "matched"
        if path == "/api/v2.0/ping" and mime == b"text/plain" and body == b"Pong":
            return "matched"
    if mime == b"application/json" and (host in DENIALS or host in (WIKI, ARGO, HARBOR)):
        try:
            data = json.loads(body, object_pairs_hook=unique_fields)
            if host == ARGO and isinstance(data, dict):
                if (
                    path == "/api/version"
                    and code == b"200"
                    and isinstance(data.get("Version"), str)
                    and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][\w.+-]+)?", data["Version"])
                ):
                    return "matched"
                if (
                    path == PATHS[ARGO]
                    and code == b"401"
                    and data
                    == {
                        "error": "no session information",
                        "message": "no session information",
                        "code": 16,
                    }
                    and type(data["code"]) is int
                ):
                    return "matched"
            if (
                registry
                and code == b"401"
                and isinstance(data, dict)
                and set(data) == {"errors"}
                and isinstance(data["errors"], list)
                and len(data["errors"]) == 1
                and isinstance(data["errors"][0], dict)
                and data["errors"][0].get("code") == "UNAUTHORIZED"
            ):
                return "matched"
            if host in DENIALS and code == b"401" and data == {"detail": DENIALS[host]}:
                return "matched"
            if (
                host == WIKI
                and code == b"200"
                and isinstance(data, dict)
                and all(
                    data.get(k, True) is v
                    for k, v in (("user", None), ("writable", False), ("bootstrap_required", False))
                )
            ):
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
            h: dict(zip(ips.values(), pool.map(lambda ip: check(h, ip), ips.values()), strict=True))
            for h in PATHS
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
    self_ip = {
        site: {
            key: before[site][key] == after[site][key] == {"A": [ip], "AAAA": []}
            for key in cases[site]
        }
        for site, ip in ips.items()
    }
    direct_pass = all(
        outcome == "matched" for answers in routes.values() for outcome in answers.values()
    )
    target_pass = direct_pass and all(all(rows.values()) for rows in self_ip.values())
    print(
        json.dumps(
            {
                "before": before,
                "https": routes,
                "after": after,
                "cases": cases,
                "selfIP": self_ip,
                "allDirectMatched": direct_pass,
                "sampledTargetMatched": target_pass,
            },
            sort_keys=True,
        )
    )
    return int(not target_pass)


if __name__ == "__main__":
    raise SystemExit(main())
