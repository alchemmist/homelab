"""Bracket anonymous HTTPS route checks with independent public DNS reads.

This is an observer, not a DNS writer, a geographic outage test or a VPN probe. Connect
only to the configured entrance addresses, never to a destination learned from
a DNS answer. Unknown IPv4/IPv6 evidence is reported without following it.
"""

import ipaddress
import json
import subprocess
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import yaml

from ci.quality import common
from ci.quality.public_dns_snapshot import EXPECTED_SITES, observe, questions
from ci.quality.public_web import CATALOG
from services.public_entry.tls_issuance import _mapping

BLOG = "www.alchemmist.xyz"
VENICE = "venice.socrat.alchemmist.xyz"
MONORI = "monori.alchemmist.xyz"
WIKI = "wiki.socrat.alchemmist.xyz"
PATHS = {BLOG: "/", VENICE: "/v1/models", MONORI: "/api/auth/me", WIKI: "/api/auth/me"}
DENIALS = {VENICE: "Missing bearer token", MONORI: "Not authenticated"}
LIMIT = 131072
BLOG_TITLE = "<title>Personal blog of Anton Grishin</title>"
WIKI_ANONYMOUS = (("user", None), ("writable", False), ("bootstrap_required", False))
# curl exit codes 0-99 are classification input, not tool failure.
CURL_EXITS = frozenset(range(256))
MSG_AMBIGUOUS_JSON = "ambiguous JSON fields"
MSG_UNREVIEWED_INVENTORY = "unreviewed inventory"
MSG_EXPECTED_REPLICA_ADDRESS = "expected a textual or numeric replica address"

DNSAnswers = dict[str, dict[str, list[str] | None]]


def unique_fields(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    """Refuse duplicated JSON fields instead of letting one overwrite a reviewed answer."""
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError(MSG_AMBIGUOUS_JSON)
    return data


def _application_matches(host: str, code: str, data: object) -> bool:
    """Require the exact reviewed denial or wiki witness document."""
    if host in DENIALS:
        return code == "401" and data == {"detail": DENIALS[host]}
    return (
        host == WIKI
        and code == "200"
        and isinstance(data, dict)
        and all(data.get(key, True) is value for key, value in WIKI_ANONYMOUS)
    )


def check(host: str, ip: str) -> str:
    """Fetch the pinned path through the fixed peer and classify it; never follow it."""
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
        response = common.command(args, allowed=CURL_EXITS, timeout=9)
    except (OSError, subprocess.TimeoutExpired):
        return "client-failed"
    if response.returncode:
        return {
            7: "connect-failed",
            28: "timeout",
            35: "tls-handshake-failed",
            60: "tls-verification-failed",
            63: "oversize",
        }.get(response.returncode, "transfer-failed")
    body, marker, metadata = response.stdout.rpartition("\n")
    code, _, declared = metadata.partition(" ")
    mime = declared.partition(";")[0].lower().strip()
    if not marker or len(body) > LIMIT:
        return "invalid-response"
    if host == BLOG and code == "200" and mime == "text/html" and BLOG_TITLE in body:
        return "matched"
    if mime == "application/json" and (host in DENIALS or host == WIKI):
        try:
            data = json.loads(body, object_pairs_hook=unique_fields)
        except (ValueError, RecursionError):
            data = None
        if _application_matches(host, code, data):
            return "matched"
    return "unexpected-application-response"


def verdict(before: object, after: object, routes: dict[str, str]) -> str:
    """Classify one DNS answer against its bracketed peers; partial matches never pass."""
    if before != after:
        return "dns-changed"
    rows = before if isinstance(before, dict) else {}
    answers = rows.get("A")
    if not answers or rows.get("AAAA") != []:
        return "dns-incomplete-or-unsupported"
    if not isinstance(answers, (list, tuple)):
        return "dns-incomplete-or-unsupported"
    names: list[str] = []
    for answer in answers:
        if not isinstance(answer, str) or answer not in routes:
            return "outside-reviewed-entrances"
        names.append(answer)
    if any(routes[name] != "matched" for name in names):
        return "advertised-path-not-verified"
    return "advertised-paths-matched"


def main() -> int:
    """Bracket every advertised HTTPS route with independent public DNS reads."""
    catalog = yaml.safe_load(CATALOG.read_text())
    ips: dict[str, str] = {}
    for site, replica in _mapping(_mapping(catalog)["replicas"]).items():
        entry = _mapping(replica)
        address_value = entry["publicIP"]
        if not isinstance(address_value, (str, int)):
            raise TypeError(MSG_EXPECTED_REPLICA_ADDRESS)
        ips[site] = str(ipaddress.IPv4Address(address_value))
    if (
        set(ips) != EXPECTED_SITES
        or len(set(ips.values())) != len(EXPECTED_SITES)
        or not set(PATHS) <= set(questions(catalog))
    ):
        raise ValueError(MSG_UNREVIEWED_INVENTORY)
    with ThreadPoolExecutor(len(EXPECTED_SITES)) as pool:

        def dns() -> dict[str, DNSAnswers]:
            """Read every site's DNS once so route checks are bracketed by them."""
            return dict(pool.map(lambda site: observe(site, ips[site], list(PATHS)), ips))

        before = dns()
        routes: dict[str, dict[str, str]] = {}
        for host in PATHS:
            peers = list(ips.values())
            routes[host] = dict(
                zip(
                    peers,
                    list(pool.map(lambda ip, _host=host: check(_host, ip), peers)),
                    strict=True,
                )
            )
        after = dns()
    cases = {
        site: {
            host + "/" + transport: verdict(
                before[site][host + "/" + transport],
                after[site][host + "/" + transport],
                routes[host],
            )
            for host in PATHS
            for transport in ("udp", "tcp")
        }
        for site in ips
    }
    self_ip = {
        site: {
            key: before[site][key] == after[site][key] == {"A": [address], "AAAA": []}
            for key in cases[site]
        }
        for site, address in ips.items()
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
