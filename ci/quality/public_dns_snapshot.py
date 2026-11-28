"""Read the public DNS wire view at the three inventory addresses; never publish.

Exit zero only for exact self-A and empty authoritative AAAA on every checked
ordinary name. A matching answer does not identify the process behind the IP,
verify delegation, change an owner's policy or prove TLS or outage independence.
"""

import ipaddress
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

import yaml

from ci.quality import common
from ci.quality.public_web import CATALOG, ZONE

MAX_NAME_LENGTH = 253
ANSWER_ROW_FIELDS = 5
EXPECTED_SITES = {"home", "nl", "moscow"}
LABEL = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"


OBJ = dict[str, object]


def questions(catalog: object) -> list[str]:
    """Return the sorted managed web names, refusing anything outside the zone."""
    shape = "catalog is not the reviewed inventory"
    if not isinstance(catalog, dict):
        raise TypeError(shape)
    web_hosts: list[object] = []
    if not isinstance(catalog.get("hosts"), dict):
        raise TypeError(shape)
    for per_site in catalog["hosts"].values():
        if not isinstance(per_site, dict):
            raise TypeError(shape)
        for host, policy in per_site.items():
            if not isinstance(policy, dict):
                raise TypeError(shape)
            if policy.get("dns") == "managed" and policy.get("route", "web") == "web":
                web_hosts.append(host)
    names = sorted({str(h) for h in web_hosts})
    reason = "unexpected managed DNS name"
    if not names or any(
        (n != ZONE and not n.endswith("." + ZONE))
        or len(n) > MAX_NAME_LENGTH
        or not all(re.fullmatch(LABEL, part) for part in n.split("."))
        for n in names
    ):
        raise ValueError(reason)
    return names


def addresses(text: str, host: str, kind: str) -> list[str]:
    """Accept only a complete, authoritative, nonrecursive address RRset or NODATA."""
    lines = text.strip().splitlines()
    headers = [s for s in lines if s.startswith(";; ->>HEADER<<-")]
    flags = [s for s in lines if s.startswith(";; flags:")]
    incomplete = "no complete NOERROR reply"
    if (
        len(headers) != 1
        or not re.fullmatch(r";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: \d+", headers[0])
        or len(flags) != 1
    ):
        raise ValueError(incomplete)
    match = re.fullmatch(
        r";; flags: ([^;]+); QUERY: 1, ANSWER: (\d+), AUTHORITY: \d+, ADDITIONAL: \d+", flags[0]
    )
    nonauthoritative = "not strictly authoritative"
    if not match or set(match[1].split()) != {"qr", "aa"}:
        raise ValueError(nonauthoritative)
    unexpected = "unexpected question section"
    if kind not in {"A", "AAAA"} or lines.count(";; QUESTION SECTION:") != 1:
        raise ValueError(unexpected)
    section = [line for line in lines[lines.index(";; QUESTION SECTION:") + 1 :] if line]
    mismatch = "question mismatch"
    if not section or section[0].split() != [";" + host + ".", "IN", kind]:
        raise ValueError(mismatch)
    count = int(match[2])
    tail = section[1:]
    missing_answer = "missing answer section"
    if count and tail[:1] != [";; ANSWER SECTION:"]:
        raise ValueError(missing_answer)
    rr = [line.split() for line in (tail[1:] if count else tail)]
    count_mismatch = "answer count mismatch"
    if len(rr) != count:
        raise ValueError(count_mismatch)
    result = []
    indirect = "non-address or indirect answer"
    for row in rr:
        if (
            len(row) != ANSWER_ROW_FIELDS
            or row[0] != host + "."
            or not row[1].isdecimal()
            or row[2:4] != ["IN", kind]
        ):
            raise ValueError(indirect)
        result.append(
            str((ipaddress.IPv4Address if kind == "A" else ipaddress.IPv6Address)(row[4]))
        )
    duplicate = "duplicate answer"
    if len(set(result)) != count:
        raise ValueError(duplicate)
    return sorted(result)


def observe(
    site: str, ip: str, names: list[str]
) -> tuple[str, dict[str, dict[str, list[str] | None]]]:
    """Query one authority replica for every managed name over UDP and TCP."""
    rows: dict[str, dict[str, list[str] | None]] = {}
    for host in names:
        for proto in ("udp", "tcp"):
            results: dict[str, list[str] | None] = {}
            for kind in ("A", "AAAA"):
                try:
                    reply = common.command(
                        [
                            "dig",
                            "@" + ip,
                            "+tcp" if proto == "tcp" else "+notcp",
                            "+ignore",
                            "+tries=1",
                            "+time=2",
                            "+noedns",
                            "+norecurse",
                            "+noall",
                            "+comments",
                            "+question",
                            "+answer",
                            host + ".",
                            kind,
                        ],
                        timeout=4,
                    )
                    results[kind] = addresses(reply.stdout, host, kind)
                except (ValueError, RuntimeError, subprocess.SubprocessError, OSError):
                    results[kind] = None
            rows[host + "/" + proto] = results
    return site, rows


def main() -> int:
    """Report the three replicas' wire views and exit non-zero on any drift."""
    catalog = yaml.safe_load(CATALOG.read_text())
    names = questions(catalog)
    ips = {s: str(ipaddress.IPv4Address(i["publicIP"])) for s, i in catalog["replicas"].items()}
    reason = "unexpected authority inventory"
    if set(ips) != EXPECTED_SITES or len(set(ips.values())) != len(EXPECTED_SITES):
        raise ValueError(reason)
    with ThreadPoolExecutor(len(EXPECTED_SITES)) as pool:
        report = dict(pool.map(lambda site: observe(site, ips[site], names), ips))
    print(json.dumps(report, sort_keys=True))
    return int(
        any(r != {"A": [ips[s]], "AAAA": []} for s, rows in report.items() for r in rows.values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
