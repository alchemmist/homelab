#!/usr/bin/env python3
"""Owned HOME→NL fixed-service DNAT via Moscow; never alters default routes.

Initial --apply requires fresh state. --boot validates the persisted exact rule
projection. A service-start failure retains a destination-specific prohibit route.
Unknown ports are intentionally NOT claimed as migrated by this tool.
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path

ROOT = Path("/var/lib/homelab-vpn-transit/home-egress")
TABLE = "homelab_msk_home_egress"
EXIT = "109.120.141.60"


def command(args: list[str]) -> str:
    """Run a fixed reviewed command and return its stdout."""
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE)


DIRECT_PROBE_UID = 19091
DIRECT_PROBE_COMMENT = "homelab-direct-ip-probe"


def rules(*, direct_probe: bool | None = None) -> str:
    """Return the reviewed nftables source for the owned egress table."""
    tcp_ports_91 = "{ 80, 443, 32053, 32083, 32084, 51840 }"
    body = (
        "\n ip daddr 109.120.141.60 tcp dport 53 counter dnat ip to 10.250.0.40:53"
        "\n ip daddr 109.120.141.60 udp dport 53 counter dnat ip to 10.250.0.40:53"
        "\n ip daddr 109.120.141.60 tcp dport " + tcp_ports_91 + " counter dnat ip to 91.189.82.238"
        "\n ip daddr 109.120.141.60 udp dport { 443, 32085, 32086 }"
        " counter dnat ip to 91.189.82.238"
        "\n ip daddr 109.120.141.60 udp dport 51830 counter dnat ip to 91.189.82.238:51832"
        "\n"
    )
    if direct_probe is None:
        direct_probe = socket.gethostname() == "socrat-0"
    bypass = (
        (
            " ip daddr 109.120.141.60 tcp dport 443 meta skuid "
            + str(DIRECT_PROBE_UID)
            + ' counter return comment "'
            + DIRECT_PROBE_COMMENT
            + '"\n'
        )
        if direct_probe
        else ""
    )
    return (
        "table inet " + TABLE + " {\n"
        " chain prerouting { type nat hook prerouting priority dstnat; policy accept;\n"
        + body
        + " }\n"
        " chain output { type nat hook output priority dstnat; policy accept;\n"
        + bypass
        + body
        + " }\n"
        " chain postrouting { type nat hook postrouting priority srcnat; policy accept;\n"
        " ip daddr 10.250.0.40 tcp dport 53 counter masquerade\n"
        " ip daddr 10.250.0.40 udp dport 53 counter masquerade\n }\n}\n"
    )


def projection() -> dict[str, object]:
    """Return the live nftables projection without volatile handles and counters."""
    value: object = json.loads(command(["nft", "-j", "list", "table", "inet", TABLE]))
    if not isinstance(value, dict):
        reason = "nft returned a non-object projection"
        raise TypeError(reason)

    def clean(v: object) -> object:
        """Drop metainfo, handles and counters, recursing into dicts and lists."""
        if isinstance(v, list):
            return [clean(x) for x in v if not isinstance(x, dict) or "metainfo" not in x]
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if k not in ("handle", "packets", "bytes")}
        return v

    typed = clean(value)
    if not isinstance(typed, dict):
        reason = "Cleaned projection is not an object"
        raise TypeError(reason)
    return typed


def upgrade_direct_probe() -> None:
    """One-shot CAS migration of HOME0's owned table; no flush/delete/reload."""
    if os.geteuid() != 0:
        reason = "The direct probe upgrade must run as root"
        raise RuntimeError(reason)
    if socket.gethostname() != "socrat-0":
        reason = "The direct probe upgrade runs only on socrat-0"
        raise RuntimeError(reason)
    os.umask(0o077)
    old = rules(direct_probe=False)
    if (ROOT / "rules.nft").read_text() != old:
        msg = "Not the reviewed legacy source"
        raise RuntimeError(msg)
    before = projection()
    if before != json.loads((ROOT / "expected.json").read_text()):
        msg = "Live drift: stop"
        raise RuntimeError(msg)
    accepted = json.loads((ROOT / "accepted.json").read_text())
    if (
        not isinstance(accepted, dict)
        or accepted.get("rules_sha256") != hashlib.sha256(old.encode()).hexdigest()
    ):
        msg = "Accepted receipt does not describe the legacy rules body"
        raise RuntimeError(msg)
    receipt = ROOT / "direct-probe-upgrade"
    if receipt.exists():
        msg = "Existing attempt: inspect receipts, never replay"
        raise RuntimeError(msg)
    receipt.mkdir(mode=0o700)
    for name in ("rules.nft", "expected.json", "accepted.json"):
        (receipt / (name + ".before")).write_bytes((ROOT / name).read_bytes())
    batch = (
        "insert rule inet "
        + TABLE
        + " output ip daddr "
        + EXIT
        + " tcp dport 443 meta skuid "
        + str(DIRECT_PROBE_UID)
        + ' counter return comment "'
        + DIRECT_PROBE_COMMENT
        + '"\n'
    )
    (receipt / "insert.nft").write_text(batch)
    command(["nft", "-c", "-f", str(receipt / "insert.nft")])
    command(["nft", "-f", str(receipt / "insert.nft")])
    after = projection()
    nftables = after["nftables"]
    if not isinstance(nftables, list):
        reason = "Unexpected nftables projection body"
        raise TypeError(reason)
    added = [
        v
        for v in nftables
        if isinstance(v, dict)
        and isinstance(v.get("rule"), dict)
        and v["rule"].get("comment") == DIRECT_PROBE_COMMENT
    ]
    expected_expr = [
        {
            "match": {
                "op": "==",
                "left": {"payload": {"protocol": "ip", "field": "daddr"}},
                "right": EXIT,
            }
        },
        {
            "match": {
                "op": "==",
                "left": {"payload": {"protocol": "tcp", "field": "dport"}},
                "right": 443,
            }
        },
        {
            "match": {
                "op": "==",
                "left": {"meta": {"key": "skuid"}},
                "right": DIRECT_PROBE_UID,
            }
        },
        {"counter": {}},
        {"return": None},
    ]
    if len(added) != 1:
        msg = "Direct probe rule must be inserted exactly once"
        raise RuntimeError(msg)
    if added[0]["rule"]["chain"] != "output":
        msg = "Direct probe rule must land in the output chain"
        raise RuntimeError(msg)
    if added[0]["rule"]["expr"] != expected_expr:
        msg = "Unexpected inserted rule: inspect"
        raise RuntimeError(msg)
    without = dict(after, nftables=[v for v in nftables if v not in added])
    if without != before:
        msg = "Unrelated change: inspect"
        raise RuntimeError(msg)
    output_rules = [v["rule"] for v in nftables if v.get("rule", {}).get("chain") == "output"]
    if output_rules[0]["comment"] != DIRECT_PROBE_COMMENT:
        msg = "Direct probe bypass must be the first output rule"
        raise RuntimeError(msg)
    new = rules(direct_probe=True)
    (ROOT / "rules.nft").write_text(new)
    (ROOT / "expected.json").write_text(json.dumps(after, sort_keys=True))
    accepted = {
        "rules_sha256": hashlib.sha256(new.encode()).hexdigest(),
        "only_owned_table_added": True,
        "direct_probe_uid": DIRECT_PROBE_UID,
        "only_home0_local_tcp443_probe_bypasses_moscow": True,
    }
    (ROOT / "accepted.json").write_text(json.dumps(accepted, sort_keys=True))
    (receipt / "accepted.json").write_text(json.dumps(accepted, sort_keys=True))
    if projection() != after:
        msg = "Live table drifted from the acknowledged projection"
        raise RuntimeError(msg)
    print(
        json.dumps(
            {
                "direct_probe_upgrade": True,
                "uid": DIRECT_PROBE_UID,
                "ordinary_traffic_unchanged": True,
            }
        )
    )


def run(*, boot: bool = False) -> None:
    """Apply or re-validate the owned egress table on the reviewed home nodes."""
    if os.geteuid() != 0:
        reason = "The egress tool must run as root"
        raise RuntimeError(reason)
    if socket.gethostname() not in ("socrat-0", "socrat-1", "socrat-3"):
        reason = "This tool only runs on the reviewed home transit nodes"
        raise RuntimeError(reason)
    os.umask(0o077)
    source = rules()
    digest = hashlib.sha256(source.encode()).hexdigest()
    if not boot:
        if json.loads(command(["ip", "-4", "-j", "route", "show", "exact", EXIT + "/32"])):
            msg = "Unowned destination route: stop"
            raise RuntimeError(msg)
        if ROOT.exists():
            msg = "Existing state; inspect instead of replaying"
            raise RuntimeError(msg)
        if (
            subprocess.run(
                ["nft", "list", "table", "inet", TABLE],
                check=False,
                capture_output=True,
            ).returncode
            == 0
        ):
            msg = "Owned nft table already exists: inspect instead of replaying"
            raise RuntimeError(msg)
        ROOT.mkdir(parents=True, mode=0o700)
        (ROOT / "rules.nft").write_text(source)
        (ROOT / "before-private.json").write_text(command(["nft", "-j", "list", "ruleset"]))
        (ROOT / "attempt.json").write_text(json.dumps({"rules_sha256": digest}))
    else:
        if not (ROOT / "accepted.json").exists():
            msg = "Unaccepted state: retain fence, inspect"
            raise RuntimeError(msg)
        if (ROOT / "rules.nft").read_text() != source:
            msg = "Persisted rules no longer match the reviewed projection"
            raise RuntimeError(msg)
    command(["nft", "-c", "-f", str(ROOT / "rules.nft")])
    present = (
        subprocess.run(
            ["nft", "list", "table", "inet", TABLE], check=False, capture_output=True
        ).returncode
        == 0
    )
    if not present:
        command(["nft", "-f", str(ROOT / "rules.nft")])
    observed = projection()
    if boot:
        if observed != json.loads((ROOT / "expected.json").read_text()):
            msg = "Unexpected live table drift"
            raise RuntimeError(msg)
    else:
        (ROOT / "expected.json").write_text(json.dumps(observed, sort_keys=True))
        (ROOT / "accepted.json").write_text(
            json.dumps({"rules_sha256": digest, "only_owned_table_added": True})
        )
        (ROOT / "attempt.json").rename(ROOT / "original-attempt.json")
    # Only the startup safety fence belonging to this service may be removed.
    fence = ["ip", "-4", "route", "del", "prohibit", EXIT + "/32", "metric", "32760"]
    removed = subprocess.run(fence, capture_output=True, check=False)
    if boot and removed.returncode != 0:
        msg = "Startup safety fence could not be removed: inspect"
        raise RuntimeError(msg)
    print(
        json.dumps(
            {
                "node": socket.gethostname(),
                "known_nl_services_via_moscow": True,
                "default_routes_unchanged": True,
                "unknown_ports_not_claimed": True,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true")
    group.add_argument("--boot", action="store_true")
    group.add_argument("--upgrade-direct-probe", action="store_true")
    args = parser.parse_args()
    if args.upgrade_direct_probe:
        upgrade_direct_probe()
    else:
        run(boot=args.boot)
