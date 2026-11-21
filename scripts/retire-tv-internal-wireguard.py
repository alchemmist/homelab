#!/usr/bin/env python3
"""Retire only the explicitly owned xiaomi-tv peer, without restarting WireGuard."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import socket
import subprocess
from pathlib import Path

KEY = "2iba8vq4KkAZmoLR+5u9t/WUlvtrHOtS+ys/k8oN4wQ="
IP = "10.250.0.8/32"
ROOT = Path("/var/lib/homelab-tv-wireguard-retirement")
CONF = Path("/etc/wireguard/wg-socrat.conf")


def need(msg: str, *, ok: bool):
    if not ok:
        raise RuntimeError(msg)


def digest(b: bytes):
    return hashlib.sha256(b).hexdigest()


def peers():
    out = subprocess.check_output(["wg", "show", "wg-socrat", "allowed-ips"], text=True)
    return dict(line.split("\t", 1) for line in out.splitlines())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    os.umask(0o077)
    need(
        "Unexpected node",
        ok=socket.gethostname().split(".")[0] in ["socrat-0", "socrat-1", "socrat-2", "socrat-3"],
    )
    need("Unsafe state", ok=not ROOT.is_symlink())
    ROOT.mkdir(mode=0o700, exist_ok=True)
    need("Unsafe state owner/mode", ok=ROOT.stat().st_uid == 0 and not ROOT.stat().st_mode & 0o077)
    with (ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        need("Uncertain previous retirement; stop", ok=not (ROOT / "uncertain.json").exists())
        need(
            "Unsafe WireGuard config",
            ok=not CONF.is_symlink()
            and CONF.stat().st_uid == 0
            and not CONF.stat().st_mode & 0o077,
        )
        before = CONF.read_bytes()
        kept = []
        count = 0
        for block in re.split(r"(?m)(?=^\[Peer\])", before.decode()):
            k = re.search(r"(?m)^PublicKey\s*=\s*(\S+)\s*$", block)
            ips = re.search(r"(?m)^AllowedIPs\s*=\s*([^\n]+)", block)
            if k and (k[1] == KEY or (ips and ips[1].strip() == IP)):
                need(
                    "Peer ownership mismatch",
                    ok=bool(
                        k[1] == KEY and ips and ips[1].strip() == IP and "# xiaomi-tv" in block
                    ),
                )
                count += 1
            else:
                kept.append(block)
        need("Duplicate owned peer", ok=count <= 1)
        after = "".join(kept).encode()
        runtime = peers()
        need(
            "Address belongs to another identity",
            ok=all(k == KEY or v.strip() != IP for k, v in runtime.items()),
        )
        need("Unexpected owned peer routes", ok=KEY not in runtime or runtime[KEY].strip() == IP)
        context = {
            "before_sha": digest(before),
            "after_sha": digest(after),
            "runtime": runtime,
            "tool_sha": digest(Path(__file__).read_bytes()),
        }
        h = digest(json.dumps(context, sort_keys=True).encode())
        changed = bool(count or KEY in runtime)
        if a.apply and changed:
            need("Fresh exact approval required", ok=a.approve_plan_hash == h)
            need(
                "Existing retirement backup; inspect before retry",
                ok=not (ROOT / "before.conf").exists(),
            )
            (ROOT / "before.conf").write_bytes(before)
            (ROOT / "before.json").write_text(json.dumps(context))
            (ROOT / "uncertain.json").write_text(json.dumps({"plan_hash": h}))
            need("Concurrent drift; stop", ok=CONF.read_bytes() == before and peers() == runtime)
            if count:
                temp = CONF.with_name("wg-socrat.conf.tv-retirement")
                need("Unexpected temporary config", ok=not temp.exists())
                temp.write_bytes(after)
                temp.chmod(0o600)
                temp.replace(CONF)
            if KEY in runtime:
                subprocess.run(
                    ["wg", "set", "wg-socrat", "peer", KEY, "remove"],
                    check=True,
                    capture_output=True,
                )
            need(
                "Other peer routes changed",
                ok=peers() == {k: v for k, v in runtime.items() if k != KEY},
            )
            need("Persistent readback failed", ok=CONF.read_bytes() == after)
            (ROOT / "after.json").write_text(
                json.dumps(
                    {"plan_hash": h, "other_peers_unchanged": True, "interface_restarted": False}
                )
            )
            (ROOT / "uncertain.json").unlink()
        print(
            json.dumps(
                {"operations": int(changed), "plan_hash": h, "applied": bool(a.apply and changed)}
            )
        )


if __name__ == "__main__":
    main()
