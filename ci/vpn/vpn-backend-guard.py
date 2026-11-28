#!/usr/bin/env python3
"""Narrow owned nft input guard: public eth0 TCP12096/32087 only.

No forwarding/NAT/443/overlay changes. Existing connections survive; new public
connections are reset. ensure is idempotent ONLY for the exact owned rules.
"""

import argparse
import importlib.util
import json
import os
import socket
import subprocess
from collections.abc import Sequence
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "inventory", Path(__file__).with_name("vpn-hardening-inventory.py")
)
if spec is None or spec.loader is None:
    msg = "Inventory module is not loadable"
    raise RuntimeError(msg)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
TABLE = "homelab_xui_backend_guard"
OWNER = "homelab issue83 public backend guard v1"


def run(args: Sequence[str], *, stdin: str | None = None) -> str:
    """Run one reviewed root operation with bounded output; never publish failure output."""
    r = subprocess.run(args, input=stdin, check=False, capture_output=True, text=True, timeout=20)
    if r.returncode:
        msg = "Backend guard operation failed; inspect private receipts"
        raise RuntimeError(msg)
    output: str = r.stdout
    return output


def rules() -> str:
    """Return the pinned guard input table, byte-for-byte identical to the reviewed nft file."""
    return (
        "table inet homelab_xui_backend_guard {\n"
        ' comment "homelab issue83 public backend guard v1"\n'
        " chain input {\n"
        "  type filter hook input priority -6; policy accept;\n"
        '  iifname "eth0" tcp dport { 12096, 32087 } ct state established '
        'counter return comment "owned83:established"\n'
        '  iifname "eth0" tcp dport { 12096, 32087 } counter reject with tcp '
        'reset comment "owned83:public-deny"\n'
        " }\n"
        "}\n"
    )


def stable(value: object) -> object:
    """Project volatile counters, handles and metainfo out of a json structure."""
    if isinstance(value, dict):
        return {
            k: stable(v)
            for k, v in value.items()
            if k not in ("packets", "bytes", "handle", "metainfo")
        }
    if isinstance(value, list):
        return [stable(x) for x in value if not (isinstance(x, dict) and "metainfo" in x)]
    return value


def expected() -> list[dict[str, object]]:
    """Return the exact nftables JSON objects this owner installed."""
    prefix = [
        {"match": {"op": "==", "left": {"meta": {"key": "iifname"}}, "right": "eth0"}},
        {
            "match": {
                "op": "==",
                "left": {"payload": {"protocol": "tcp", "field": "dport"}},
                "right": {"set": [12096, 32087]},
            }
        },
    ]
    objects: list[dict[str, object]] = [
        {"table": {"family": "inet", "name": TABLE}},
        {
            "chain": {
                "family": "inet",
                "table": TABLE,
                "name": "input",
                "type": "filter",
                "hook": "input",
                "prio": -6,
                "policy": "accept",
            }
        },
        {
            "rule": {
                "family": "inet",
                "table": TABLE,
                "chain": "input",
                "comment": "owned83:established",
                "expr": [
                    *prefix,
                    {
                        "match": {
                            "op": "in",
                            "left": {"ct": {"key": "state"}},
                            "right": "established",
                        }
                    },
                    {"counter": {}},
                    {"return": None},
                ],
            }
        },
        {
            "rule": {
                "family": "inet",
                "table": TABLE,
                "chain": "input",
                "comment": "owned83:public-deny",
                "expr": [*prefix, {"counter": {}}, {"reject": {"type": "tcp reset"}}],
            }
        },
    ]
    return objects


def validate(objects: list[dict[str, object]]) -> None:
    """Require the observed table to contain exactly this owner's reviewed rules."""
    data = stable(objects)
    if not isinstance(data, list):
        reason = "Unexpected nftables objects projection"
        raise TypeError(reason)
    for obj in data:
        if "table" in obj:
            comment = obj["table"].pop("comment", None)
            if comment not in (None, OWNER):
                msg = "Foreign table owner"
                raise ValueError(msg)
    # NetBird inserts this exact private-interface accept into input hook chains.
    # It cannot match eth0 and is redundant with this chain's accept policy.
    # Preserve it; allow no other foreign rule, duplicate, interface or verdict.
    private_allow = {
        "rule": {
            "family": "inet",
            "table": TABLE,
            "chain": "input",
            "expr": [
                {
                    "match": {
                        "op": "==",
                        "left": {"meta": {"key": "iifname"}},
                        "right": "nb-host",
                    }
                },
                {"counter": {}},
                {"accept": None},
            ],
        }
    }
    if data.count(private_allow) > 1:
        msg = "Duplicate private interface allowance"
        raise ValueError(msg)
    data = [obj for obj in data if obj != private_allow]
    if data != expected():
        msg = "Not the exact owned backend guard"
        raise ValueError(msg)


def read_table() -> list[dict[str, object]] | None:
    """Read and validate this owner's table objects, or None when absent."""
    data = json.loads(run(["nft", "-j", "list", "ruleset"]))["nftables"]
    own = [
        x
        for x in data
        if any(
            isinstance(v, dict)
            and v.get("family") == "inet"
            and (v.get("table") == TABLE or (k == "table" and v.get("name") == TABLE))
            for k, v in x.items()
        )
    ]
    if own:
        validate(own)
    return own or None


def require_host() -> None:
    """Refuse to run anywhere but root on socrat-2 with its public interface."""
    if os.geteuid() != 0 or socket.gethostname() != "socrat-2":
        msg = "Requires root on socrat-2"
        raise ValueError(msg)
    links = json.loads(run(["ip", "-j", "link", "show", "eth0"]))
    if len(links) != 1 or links[0]["ifname"] != "eth0":
        msg = "Public interface missing"
        raise ValueError(msg)


def plan() -> dict[str, object]:
    """Publish the exact intended guard change without applying it."""
    require_host()
    current = read_table()
    return {
        "table": TABLE,
        "interface": "eth0",
        "ports": [12096, 32087],
        "rules_sha256": h.digest(rules()),
        "before_sha256": h.digest(stable(current)),
        "preserve_established": True,
        "forwarding_or_nat_changes": False,
        "packet_logging": False,
    }


def apply(state: Path, approval: str) -> dict[str, object]:
    """Apply the approved rules once, leaving private receipts behind."""
    require_host()
    wanted = plan()
    if h.digest(wanted) != approval or read_table() is not None:
        msg = "Fresh empty-table approval required"
        raise ValueError(msg)
    run(["nft", "--check", "-f", "-"], stdin=rules())
    h.save(state / "backend-guard-before.json", None)
    h.save(state / "backend-guard-uncertain.json", {"approval": approval, "plan": wanted})
    if plan() != wanted:
        msg = "Preimage drift"
        raise ValueError(msg)
    run(["nft", "-f", "-"], stdin=rules())
    after = read_table()
    if after is None:
        msg = "Guard not present"
        raise RuntimeError(msg)
    h.save(state / "backend-guard-after.json", after)
    h.save(state / "backend-guard-receipt.json", wanted)
    (state / "backend-guard-uncertain.json").unlink()
    return wanted


def finalize_readback(state: Path, approval: str) -> dict[str, object]:
    """Finalize an interrupted apply from its private readback markers."""
    require_host()
    marker = json.loads((state / "backend-guard-uncertain.json").read_text())
    if marker["approval"] != approval or h.digest(marker["plan"]) != approval:
        msg = "Interrupted approval mismatch"
        raise ValueError(msg)
    if marker["plan"]["rules_sha256"] != h.digest(rules()) or marker["plan"][
        "before_sha256"
    ] != h.digest(None):
        msg = "Interrupted rules/preimage mismatch"
        raise ValueError(msg)
    if json.loads((state / "backend-guard-before.json").read_text()) is not None:
        msg = "Nonempty original table"
        raise ValueError(msg)
    current = read_table()
    if current is None:
        msg = "No installed guard; do not replay"
        raise ValueError(msg)
    h.save(state / "backend-guard-after.json", current)
    h.save(
        state / "backend-guard-receipt.json",
        dict(marker["plan"], readback_finalized=True, repeated_rule_writes=0),
    )
    (state / "backend-guard-uncertain.json").unlink()
    return {"readback_finalized": True, "repeated_rule_writes": 0}


def ensure() -> dict[str, object]:
    """Idempotently verify the owned boot guard, applying it once when absent."""
    require_host()
    if read_table() is None:
        run(["nft", "--check", "-f", "-"], stdin=rules())
        run(["nft", "-f", "-"], stdin=rules())
        if read_table() is None:
            msg = "Boot guard missing"
            raise RuntimeError(msg)
    return {"owned_guard_present": True}


UNIT = """[Unit]
Description=Homelab private VPN backend public-input guard
Wants=network-online.target
After=network-online.target nftables.service
Before=k3s.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3\
 /usr/local/libexec/homelab-vpn-backend-guard/vpn-backend-guard.py --ensure

[Install]
WantedBy=multi-user.target
"""


def persist(state: Path) -> None:
    """Copy the verified guard to the host and enable its boot unit, exactly once."""
    require_host()
    if read_table() is None:
        msg = "Verified live guard required before persistence"
        raise ValueError(msg)
    dest = h.private_directory("/usr/local/libexec/homelab-vpn-backend-guard")
    files = {
        dest / "vpn-backend-guard.py": Path(__file__).read_bytes(),
        dest / "vpn-hardening-inventory.py": Path(__file__)
        .with_name("vpn-hardening-inventory.py")
        .read_bytes(),
        Path("/etc/systemd/system/homelab-xui-backend-guard.service"): UNIT.encode(),
    }
    for path in files:
        h.check_path(path)
        if path.exists():
            msg = "Persistence path already exists; inspect instead of overwriting"
            raise ValueError(msg)
    h.save(state / "guard-persistence-uncertain.json", {"paths": [str(p) for p in files]})
    for path, content in files.items():
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600 if path.parent == dest else 0o644,
        )
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    run(
        [
            "systemd-analyze",
            "verify",
            "/etc/systemd/system/homelab-xui-backend-guard.service",
        ]
    )
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "homelab-xui-backend-guard.service"])
    run(["systemctl", "is-enabled", "homelab-xui-backend-guard.service"])
    run(["systemctl", "is-active", "homelab-xui-backend-guard.service"])
    read_table()
    h.save(
        state / "guard-persistence-receipt.json",
        {"enabled": True, "active": True, "reboot_tested": False},
    )
    (state / "guard-persistence-uncertain.json").unlink()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ensure", action="store_true")
    a = p.parse_args()
    if a.ensure:
        print(h.canonical(ensure()))
    else:
        print(h.canonical(plan()))
