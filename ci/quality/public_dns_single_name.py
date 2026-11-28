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

from ci.quality.closed_root_owners import eligible, owner_render
from ci.quality.public_dns_snapshot import EXPECTED_SITES
from ci.quality.public_web import CATALOG, ROOT
from services.public_entry.tls_issuance import _mapping

OWNER = "www"
HOST = "www.alchemmist.xyz"
REVIEWED_BLOG_ENTRY = {"dns": "managed", "tlsSourceName": "blog-tls"}
WWW_ADDRESS_COLUMNS = 4
MAX_SERIAL = 2**32
MSG_UNEXPECTED_ZONE_DELTA = "unexpected zone delta"
MSG_INVALID_SERIAL_OR_DIGEST = "invalid serial or digest"
MSG_UNREVIEWED_ORDINARY_NAME = "unreviewed ordinary name"
MSG_BLOG_RELEASE_CHANGED = "current blog release no longer admits the reviewed www route"
MSG_AMBIGUOUS_CANDIDATE = "ambiguous candidate"
MSG_DIGEST_NO_MATCH = "zone digest does not match any legacy rendering; do not assume a baseline"
MSG_EXPECTED_REPLICA_ADDRESS = "expected a textual or numeric replica address"


def delta(old: str, new: str, ip: str, serial: int) -> dict[str, object]:
    """Permit only a change in the complete www A RRset between these renderings."""

    def split(zone: str) -> tuple[list[str], list[str]]:
        rows: list[str] = []
        addresses: list[str] = []
        for row in zone.splitlines(keepends=True):
            parts = row.split()
            if parts[:3] == [OWNER, "IN", "A"] and len(parts) == WWW_ADDRESS_COLUMNS:
                addresses.append(parts[3])
            else:
                rows.append(row)
        return rows, sorted(addresses)

    before, previous = split(old)
    after, current = split(new)
    if before != after or not previous or len(previous) != len(set(previous)) or current != [ip]:
        raise ValueError(MSG_UNEXPECTED_ZONE_DELTA)
    return {
        "serial": serial,
        "previous": previous,
        "candidate": [ip],
        "unchangedOtherLines": len(before),
    }


def rehearse(catalog: dict[str, object], site: str, serial: int, digest: str) -> dict[str, object]:
    """Rehearse the offline one-name delta and return its matched legacy render states."""
    if (
        type(serial) is not int
        or not 0 < serial < MAX_SERIAL
        or not re.fullmatch("[0-9a-f]{64}", digest)
    ):
        raise ValueError(MSG_INVALID_SERIAL_OR_DIGEST)
    hosts = _mapping(catalog["hosts"])
    blog = _mapping(hosts["blog"])
    if site not in EXPECTED_SITES or blog.get(HOST) != REVIEWED_BLOG_ENTRY:
        raise ValueError(MSG_UNREVIEWED_ORDINARY_NAME)
    if not eligible(owner_render(owner="blog"), catalog, owner="blog"):
        raise ValueError(MSG_BLOG_RELEASE_CHANGED)
    replicas = _mapping(catalog["replicas"])
    replica = _mapping(replicas[site])
    address_value = replica["publicIP"]
    if not isinstance(address_value, (str, int)):
        raise TypeError(MSG_EXPECTED_REPLICA_ADDRESS)
    ip = str(ipaddress.IPv4Address(address_value))
    render = runpy.run_path(str(ROOT / "ansible/scripts/public_dns_zone.py"))["render"]
    result: dict[str, object] | None = None
    matches = 0
    for home, nl, mhome, mmoscow in itertools.product((False, True), repeat=4):
        kwargs = {"monori_health": (mhome, mmoscow)}
        old = render(serial, home, nl, **kwargs)
        if hashlib.sha256(old.encode()).hexdigest() != digest:
            continue
        candidate = render(serial, home, nl, **kwargs, web_answers={OWNER: ip})
        d = delta(old, candidate, ip, serial)
        if result is not None and result != d:
            raise ValueError(MSG_AMBIGUOUS_CANDIDATE)
        result = d
        matches += 1
    if result is None:
        raise ValueError(MSG_DIGEST_NO_MATCH)
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
