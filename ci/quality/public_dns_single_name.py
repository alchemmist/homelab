"""Rehearse a one-name DNS delta offline against the exact legacy zone digest.

No SSH, DNS query, serial allocation, output zone or publisher. Input is only a
serial and SHA256 of one atomic public zone-file read. A match is render parity,
not writer approval or evidence the bytes reached a public socket.
"""

import argparse
import hashlib
import ipaddress
import itertools
import json
import re
import runpy

import yaml

from ci.quality.public_web import CATALOG, ROOT

OWNER = "www"
HOST = "www.alchemmist.xyz"


def delta(old, new, ip, serial):
    """Only a change in the complete www A RRset is permitted in these renderings."""

    def split(zone):
        rows = []
        addresses = []
        for row in zone.splitlines(keepends=True):
            parts = row.split()
            if parts[:3] == [OWNER, "IN", "A"] and len(parts) == 4:
                addresses.append(parts[3])
            else:
                rows.append(row)
        return rows, sorted(addresses)

    before, previous = split(old)
    after, current = split(new)
    if before != after or not previous or len(previous) != len(set(previous)) or current != [ip]:
        raise ValueError("unexpected zone delta")
    return {
        "serial": serial,
        "previous": previous,
        "candidate": [ip],
        "unchangedOtherLines": len(before),
    }


def rehearse(catalog, site, serial, digest):
    if (
        type(serial) is not int
        or not 0 < serial < 2**32
        or not re.fullmatch("[0-9a-f]{64}", digest)
    ):
        raise ValueError("invalid serial or digest")
    if site not in {"home", "nl", "moscow"} or catalog["hosts"]["blog"].get(HOST) != {
        "dns": "managed",
        "tlsSourceName": "blog-tls",
    }:
        raise ValueError("unreviewed ordinary name")
    ip = str(ipaddress.IPv4Address(catalog["replicas"][site]["publicIP"]))
    render = runpy.run_path(str(ROOT / "ansible/scripts/public_dns_zone.py"))["render"]
    result = None
    matches = 0
    for home, nl, mhome, mmoscow in itertools.product((False, True), repeat=4):
        kwargs = {"monori_health": (mhome, mmoscow)}
        old = render(serial, home, nl, **kwargs)
        if hashlib.sha256(old.encode()).hexdigest() != digest:
            continue
        candidate = render(serial, home, nl, **kwargs, web_answers={OWNER: ip})
        d = delta(old, candidate, ip, serial)
        if result is not None and result != d:
            raise ValueError("ambiguous candidate")
        result = d
        matches += 1
    if result is None:
        raise ValueError(
            "zone digest does not match any legacy rendering; do not assume a baseline"
        )
    return {**result, "host": HOST, "compatibleInputStates": matches}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", choices=("home", "nl", "moscow"))
    parser.add_argument("serial", type=int)
    parser.add_argument("digest")
    args = parser.parse_args()
    print(
        json.dumps(
            rehearse(yaml.safe_load(CATALOG.read_text()), args.site, args.serial, args.digest)
        )
    )
