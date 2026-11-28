#!/usr/bin/env python3
"""Add the authorized socrat-4 peer only; preserve every existing WG peer."""

import hashlib
import ipaddress
import json
import os
import re
import subprocess
from pathlib import Path
from typing import cast

KEY = "rOXEc8nrYHuYG0D5t+LwY9jxv05zsjxt0P2scF+Sf0k="
ADDRESS = "10.250.0.40/32"
ENDPOINT = "91.189.82.238:51830"
PEER_BLOCK = (
    f"\n\n# homelab socrat-4 transit worker\n[Peer]\nPublicKey = {KEY}\n"
    f"AllowedIPs = {ADDRESS}\nEndpoint = {ENDPOINT}\nPersistentKeepalive = 25\n"
)


def active_peers() -> dict[str, str]:
    """Return the current wg-socrat peer key to allowed-ips mapping."""
    lines = subprocess.check_output(
        ["wg", "show", "wg-socrat", "allowed-ips"], text=True
    ).splitlines()
    return dict(line.split(None, 1) for line in lines)


def scan_existing_peers(
    old: bytes,
    *,
    target: ipaddress.IPv4Network,
    legacy_target: ipaddress.IPv4Network,
    legacy_owned: bool,
) -> list[dict[str, str]]:
    """Parse existing peers and refuse any overlap with the new address."""
    matches = []
    for block in re.split(r"(?m)^\s*\[Peer\]\s*$", old.decode())[1:]:
        fields = {}
        for line in block.splitlines():
            content = line.split("#", 1)[0].strip()
            if "=" in content:
                k, v = content.split("=", 1)
                fields[k.strip()] = v.strip()
        networks = [
            ipaddress.ip_network(v.strip())
            for v in fields.get("AllowedIPs", "").split(",")
            if v.strip()
        ]
        if fields.get("PublicKey") == KEY:
            proper = networks == [target] or (legacy_owned and networks == [legacy_target])
            if not proper:
                msg = "Existing target peer differs"
                raise RuntimeError(msg)
            matches.append(dict(fields))
        else:
            overlapping = any(n.version == target.version and n.overlaps(target) for n in networks)
            if overlapping:
                msg = "Address overlap"
                raise RuntimeError(msg)
    if len(matches) > 1:
        msg = "More than one existing target peer"
        raise RuntimeError(msg)
    return matches


def _require_reserved_acl(acl: Path) -> None:
    """Refuse to run while the historical restricted client ACL holds our target."""
    if "10.250.0.40" in acl.read_text():
        msg = "Reserved client ACL address"
        raise RuntimeError(msg)


def _require_runtime_peers(
    runtime: dict[str, str],
    target: ipaddress.IPv4Network,
    legacy_target: ipaddress.IPv4Network,
    *,
    legacy_owned: bool,
) -> None:
    """Require the runtime peers to match the reviewed address and not overlap."""
    for key, addresses in runtime.items():
        if key == KEY:
            unchanged = addresses == ADDRESS or (legacy_owned and addresses == str(legacy_target))
            if not unchanged:
                msg = "Runtime target peer differs from the reviewed address"
                raise RuntimeError(msg)
        else:
            for entry in addresses.replace(",", " ").split():
                if (
                    entry != "(none)"
                    and ":" not in entry
                    and ipaddress.ip_network(entry).overlaps(target)
                ):
                    msg = "Address overlap"
                    raise RuntimeError(msg)


def main() -> None:
    """Execute main."""
    os.umask(0o077)
    config = Path("/etc/wireguard/wg-socrat.conf")
    old = config.read_bytes()
    target = cast("ipaddress.IPv4Network", ipaddress.ip_network(ADDRESS))
    legacy_target = cast("ipaddress.IPv4Network", ipaddress.ip_network("10.250.0.8/32"))
    prior_path = Path("/var/lib/homelab-recovery/20261109-socrat4-peer/receipt.json")
    legacy_owned = prior_path.exists() and json.loads(prior_path.read_text()).get("new_peer") == KEY
    matches = scan_existing_peers(
        old, target=target, legacy_target=legacy_target, legacy_owned=legacy_owned
    )

    # A historical restricted admin-client ACL used .8 even though its WG peer
    # was retired. Do not remove that ACL or grant a server identity to a client.
    acl = Path("/usr/local/libexec/wg-socrat-admin-firewall")
    if acl.exists():
        _require_reserved_acl(acl)
    before = active_peers()
    _require_runtime_peers(before, target, legacy_target, legacy_owned=legacy_owned)
    if matches and before.get(KEY) == ADDRESS:
        print(json.dumps({"already_present": True, "existing_peers_preserved": True}))
        return
    state = Path("/var/lib/homelab-recovery/20261109-socrat4-peer-address40")
    state.mkdir(mode=0o700, exist_ok=True)
    if (state / "attempt.json").exists():
        msg = "Uncertain prior attempt; inspect, never replay"
        raise RuntimeError(msg)
    with (state / "wg-socrat-before-private.conf").open("xb") as f:
        f.write(old)
    (state / "attempt.json").write_text(
        json.dumps(
            {
                "config_sha256": hashlib.sha256(old).hexdigest(),
                "new_peer": KEY,
                "address": ADDRESS,
            }
        )
    )
    changing_address = bool(matches) and before.get(KEY) == str(legacy_target)
    if not matches or changing_address:
        if changing_address:
            needle = ("PublicKey = " + KEY + "\nAllowedIPs = " + str(legacy_target)).encode()
            if old.count(needle) != 1:
                msg = "Existing peer block needle mismatch"
                raise RuntimeError(msg)
            new = old.replace(needle, ("PublicKey = " + KEY + "\nAllowedIPs = " + ADDRESS).encode())
        else:
            new = old.rstrip() + PEER_BLOCK.encode()
        temp = config.with_name("wg-socrat.conf.edge-once")
        with temp.open("xb") as f:
            f.write(new)
            f.flush()
            os.fsync(f.fileno())
        if config.read_bytes() != old:
            msg = "Config changed during preparation"
            raise RuntimeError(msg)
        temp.replace(config)
        fd = os.open(str(config.parent), os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    subprocess.run(
        [
            "wg",
            "set",
            "wg-socrat",
            "peer",
            KEY,
            "allowed-ips",
            ADDRESS,
            "endpoint",
            ENDPOINT,
            "persistent-keepalive",
            "25",
        ],
        check=True,
        timeout=10,
    )
    after = active_peers()
    if after.get(KEY) != ADDRESS:
        msg = "Peer not active after apply"
        raise RuntimeError(msg)
    if not all(after.get(key) == value for key, value in before.items() if key != KEY):
        msg = "Existing peers changed during apply"
        raise RuntimeError(msg)
    receipt = {
        "new_peer": KEY,
        "address": ADDRESS,
        "existing_peers_preserved": True,
        "no_interface_restart": True,
    }
    (state / "receipt.json").write_text(json.dumps(receipt))
    (state / "attempt.json").rename(state / "original-attempt.json")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
