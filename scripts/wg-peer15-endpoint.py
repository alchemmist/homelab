#!/usr/bin/env python3
"""Change only node5's peer1 endpoint, without wg-quick/network restarts.

Private config preimage remains root-only on node5. Never emit config/key data.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

PEER = "b2yWaBu06tk67Tx1N1SUktl0DntkcnKU36tIKLiqM0c="
DIRECT = "109.173.40.247:51831"
RELAY = "10.250.0.1:51835"
CONFIG = Path("/etc/wireguard/wg-socrat.conf")
BACKUP = Path("/root/.local/state/homelab-wg15-relay-20261116")


def replace_endpoint(text, target):
    """Preserve every other byte; refuse unknown or ambiguous peer state."""
    parts = re.split(r"(?m)(?=^\[Peer\]\s*$)", text)
    found = 0
    for i, part in enumerate(parts):
        keys = re.findall(r"(?m)^PublicKey[ \t]*=[ \t]*(\S+)[ \t]*$", part)
        if PEER not in keys:
            continue
        if keys != [PEER]:
            raise ValueError("Ambiguous peer block")
        matches = list(re.finditer(r"(?m)^(Endpoint[ \t]*=[ \t]*)(\S+)([ \t]*)$", part))
        if len(matches) != 1 or matches[0].group(2) not in (DIRECT, RELAY):
            raise ValueError("Unknown or ambiguous endpoint preimage")
        m = matches[0]
        parts[i] = part[: m.start(2)] + target + part[m.end(2) :]
        found += 1
    if found != 1:
        raise ValueError("Expected exactly one peer1 block")
    return "".join(parts)


def wg(*args):
    return subprocess.check_output(["wg", *args], text=True).strip()


def atomic_write(data):
    fd, name = tempfile.mkstemp(prefix=".homelab-wg15-", dir=CONFIG.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, 0o600)
        os.replace(name, CONFIG)
        directory = os.open(CONFIG.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["apply", "rollback"])
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Root required, not a setuid helper")
    target = RELAY if args.mode == "apply" else DIRECT
    st = CONFIG.stat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o600:
        raise RuntimeError("Unexpected config ownership/mode")
    original = CONFIG.read_bytes()
    text = original.decode("utf-8")
    if re.search(r"(?mi)^SaveConfig\s*=\s*true\s*$", text):
        raise RuntimeError("SaveConfig would override reviewed endpoint")
    addresses = json.loads(
        subprocess.check_output(["ip", "-j", "-4", "addr", "show", "dev", "wg-socrat"])
    )
    if "10.250.0.41" not in [a["local"] for d in addresses for a in d["addr_info"]]:
        raise RuntimeError("This command is restricted to node5")
    changed = replace_endpoint(text, target).encode("utf-8")
    allowed_before = wg("show", "wg-socrat", "allowed-ips")
    current = dict(l.split() for l in wg("show", "wg-socrat", "endpoints").splitlines())[PEER]
    if current not in (DIRECT, RELAY):
        raise RuntimeError("Unreviewed runtime peer endpoint")
    BACKUP.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(BACKUP, 0o700)
    preimage = BACKUP / "wg-socrat-before-private.conf"
    if args.mode == "apply" and not preimage.exists():
        if replace_endpoint(text, DIRECT).encode() != original:
            raise RuntimeError("Missing original direct preimage")
        with preimage.open("xb") as f:
            os.chmod(preimage, 0o600)
            f.write(original)
            f.flush()
            os.fsync(f.fileno())
    if changed != original:
        atomic_write(changed)
    try:
        wg("set", "wg-socrat", "peer", PEER, "endpoint", target)
        # Establish the symmetric authenticated path so peer roaming cannot
        # silently leave the far end pointing at the previous transport.
        for attempt in range(3):
            subprocess.run(
                ["ping", "-n", "-c", "10", "-i", "0.2", "-W", "1", "10.250.0.3"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
            )
            actual = dict(l.split() for l in wg("show", "wg-socrat", "endpoints").splitlines())[
                PEER
            ]
            if actual == target:
                break
            wg("set", "wg-socrat", "peer", PEER, "endpoint", target)
        else:
            raise RuntimeError("Authenticated path did not settle on target")
        if wg("show", "wg-socrat", "allowed-ips") != allowed_before:
            raise RuntimeError("Unexpected concurrent peer/AllowedIPs change")
    except Exception:
        atomic_write(original)
        wg("set", "wg-socrat", "peer", PEER, "endpoint", current)
        raise
    print(
        json.dumps(
            {
                "mode": args.mode,
                "endpoint": target,
                "configChanged": original != changed,
                "otherConfigBytesPreserved": True,
                "allowedIPsUnchanged": True,
                "beforeSHA256": hashlib.sha256(original).hexdigest(),
                "afterSHA256": hashlib.sha256(changed).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
