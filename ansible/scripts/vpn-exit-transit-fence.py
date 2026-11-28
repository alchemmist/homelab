#!/usr/bin/env python3
"""Close direct WAN raw VPN ingress on NL, not shared HTTPS/DNS/management.

Only the new owned table is changed. An existing table must match its accepted
counter-independent projection. No client database or existing firewall mutation.
"""

import argparse
import json
import os
import socket
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path("/var/lib/homelab-vpn-transit/exit-fence")
TABLE = "homelab_msk_exit_fence"
RULES = """table inet homelab_msk_exit_fence {
 chain input { type filter hook input priority -5; policy accept;
  iifname "eth0" tcp dport { 32053, 32083, 32084 } counter drop
  iifname "eth0" udp dport { 32085, 32086 } counter drop
 }
}
"""


def command(args: "Sequence[str]") -> str:
    """Run one reviewed command and return its stdout."""
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE)


def projection() -> object:
    """Project the live fence table without counters or metainfo."""
    value = json.loads(command(["nft", "-j", "list", "table", "inet", TABLE]))

    def clean(v: object) -> object:
        if isinstance(v, list):
            return [clean(x) for x in v if not isinstance(x, dict) or "metainfo" not in x]
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if k not in ("handle", "packets", "bytes")}
        result: object = v
        return result

    return clean(value)


def _require_root_on_exit_host() -> None:
    """Require root on the reviewed exit host before any fence change."""
    if os.geteuid() != 0:
        msg = "The exit fence must be applied as root"
        raise RuntimeError(msg)
    if socket.gethostname() != "socrat-2":
        msg = "The exit fence belongs on the reviewed exit host only"
        raise RuntimeError(msg)


def _require_wan_routes_clean() -> None:
    """Require the reviewed WAN interface and no earlier apply state."""
    route = json.loads(command(["ip", "-j", "route", "get", "91.189.82.238"]))
    if route[0]["dev"] != "eth0":
        msg = "WAN interface changed; inspect rather than guess"
        raise RuntimeError(msg)
    if ROOT.exists():
        msg = "Existing apply state; inspect, never replay"
        raise RuntimeError(msg)
    if (
        subprocess.run(
            ["nft", "list", "table", "inet", TABLE],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    ):
        msg = "Fence table already exists; inspect rather than guess"
        raise RuntimeError(msg)


def require_boot_accepted() -> None:
    """Require the stored apply receipts for the boot verification path."""
    if not (ROOT / "accepted.json").exists():
        msg = "Boot verification requires a previously accepted apply"
        raise RuntimeError(msg)
    if (ROOT / "rules.nft").read_text() != RULES:
        msg = "Stored fence rules drifted from the reviewed ruleset"
        raise RuntimeError(msg)


def run(*, boot: bool = False) -> None:
    """Apply or re-verify the reviewed raw WAN VPN ingress fence."""
    _require_root_on_exit_host()
    os.umask(0o077)
    if not boot:
        _require_wan_routes_clean()
        ROOT.mkdir(parents=True, mode=0o700)
        (ROOT / "before-private.json").write_text(command(["nft", "-j", "list", "ruleset"]))
        (ROOT / "rules.nft").write_text(RULES)
        (ROOT / "attempt.json").write_text(json.dumps({"only_raw_wan_vpn_ports": True}))
    else:
        require_boot_accepted()
    command(["nft", "-c", "-f", str(ROOT / "rules.nft")])
    if (
        subprocess.run(
            ["nft", "list", "table", "inet", TABLE], check=False, capture_output=True
        ).returncode
        != 0
    ):
        command(["nft", "-f", str(ROOT / "rules.nft")])
    observed = projection()
    if boot:
        if observed != json.loads((ROOT / "expected.json").read_text()):
            msg = "Unexpected table drift"
            raise RuntimeError(msg)
    else:
        (ROOT / "expected.json").write_text(json.dumps(observed))
        (ROOT / "accepted.json").write_text(
            json.dumps({"wan_raw_vpn_closed": True, "shared_443_unchanged": True})
        )
        (ROOT / "attempt.json").rename(ROOT / "original-attempt.json")
    print(json.dumps({"wan_raw_vpn_closed": True, "shared_443_dns_management_unchanged": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true")
    group.add_argument("--boot", action="store_true")
    args = parser.parse_args()
    run(boot=args.boot)
