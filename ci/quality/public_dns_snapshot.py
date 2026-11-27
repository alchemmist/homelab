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

from ci.quality.public_web import CATALOG, ZONE


def questions(catalog):
    names = sorted(
        {
            h
            for hosts in catalog["hosts"].values()
            for h, p in hosts.items()
            if p["dns"] == "managed" and p.get("route", "web") == "web"
        }
    )
    if not names or any(
        (n != ZONE and not n.endswith("." + ZONE))
        or len(n) > 253
        or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", l) for l in n.split("."))
        for n in names
    ):
        raise ValueError("unexpected managed DNS name")
    return names


def addresses(text, host, kind):
    """Accept only a complete, authoritative, nonrecursive address RRset or NODATA."""
    lines = text.strip().splitlines()
    headers = [s for s in lines if s.startswith(";; ->>HEADER<<-")]
    flags = [s for s in lines if s.startswith(";; flags:")]
    if (
        len(headers) != 1
        or not re.fullmatch(r";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: \d+", headers[0])
        or len(flags) != 1
    ):
        raise ValueError("no complete NOERROR reply")
    match = re.fullmatch(
        r";; flags: ([^;]+); QUERY: 1, ANSWER: (\d+), AUTHORITY: \d+, ADDITIONAL: \d+", flags[0]
    )
    if not match or set(match[1].split()) != {"qr", "aa"}:
        raise ValueError("not strictly authoritative")
    if kind not in {"A", "AAAA"} or lines.count(";; QUESTION SECTION:") != 1:
        raise ValueError("unexpected question section")
    section = [line for line in lines[lines.index(";; QUESTION SECTION:") + 1 :] if line]
    if not section or section[0].split() != [";" + host + ".", "IN", kind]:
        raise ValueError("question mismatch")
    count = int(match[2])
    tail = section[1:]
    if count and tail[:1] != [";; ANSWER SECTION:"]:
        raise ValueError("missing answer section")
    rr = [line.split() for line in (tail[1:] if count else tail)]
    if len(rr) != count:
        raise ValueError("answer count mismatch")
    result = []
    for row in rr:
        if (
            len(row) != 5
            or row[0] != host + "."
            or not row[1].isdecimal()
            or row[2:4] != ["IN", kind]
        ):
            raise ValueError("non-address or indirect answer")
        result.append(
            str((ipaddress.IPv4Address if kind == "A" else ipaddress.IPv6Address)(row[4]))
        )
    if len(set(result)) != count:
        raise ValueError("duplicate answer")
    return sorted(result)


def observe(site, ip, names):
    rows = {}
    for host in names:
        for proto in ("udp", "tcp"):
            results = {}
            for kind in ("A", "AAAA"):
                try:
                    reply = subprocess.check_output(
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
                        text=True,
                        timeout=4,
                        stderr=subprocess.DEVNULL,
                    )
                    results[kind] = addresses(reply, host, kind)
                except (ValueError, subprocess.SubprocessError, OSError):
                    results[kind] = None
            rows[host + "/" + proto] = results
    return site, rows


def main():
    catalog = yaml.safe_load(CATALOG.read_text())
    names = questions(catalog)
    ips = {s: str(ipaddress.IPv4Address(i["publicIP"])) for s, i in catalog["replicas"].items()}
    if set(ips) != {"home", "nl", "moscow"} or len(set(ips.values())) != 3:
        raise ValueError("unexpected authority inventory")
    with ThreadPoolExecutor(3) as pool:
        report = dict(pool.map(lambda site: observe(site, ips[site], names), ips))
    print(json.dumps(report, sort_keys=True))
    return int(
        any(r != {"A": [ips[s]], "AAAA": []} for s, rows in report.items() for r in rows.values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
