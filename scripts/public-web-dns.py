#!/usr/bin/env python3
"""Add only kuma.socrat to the existing authoritative renderer; zone refresh, no restart."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import types
from pathlib import Path

CURRENT = Path("/usr/local/libexec/public_dns_zone.py")
ROOT = Path("/var/lib/homelab-public-web-dns")


def require(message: str, *, ok: bool):
    if not ok:
        raise RuntimeError(message)


def load(path: Path, name: str):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def delta(old: types.ModuleType, new: types.ModuleType):
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        before = old.render(123, home_up=home, vps_up=vps).splitlines()
        after = new.render(123, home_up=home, vps_up=vps).splitlines()
        require(
            "Unrelated DNS record change; stop",
            ok=[x for x in after if not x.startswith("kuma.socrat IN A ")]
            == [x for x in before if not x.startswith("kuma.socrat IN A ")],
        )
        require(
            "Wrong new record",
            ok=[x for x in after if x.startswith("kuma.socrat IN A ")]
            == ["kuma.socrat IN A " + a for a in old.healthy_addresses(home_up=home, vps_up=vps)],
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    os.umask(0o077)
    proposed = ROOT / "proposed.py"
    for path in [CURRENT, proposed]:
        require(
            "Unsafe renderer",
            ok=path.is_file()
            and not path.is_symlink()
            and path.stat().st_uid == 0
            and not path.stat().st_mode & 0o022,
        )
    require(
        "Unsafe state directory", ok=ROOT.stat().st_uid == 0 and not ROOT.stat().st_mode & 0o077
    )
    with (ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        require("Uncertain prior write; stop", ok=not (ROOT / "uncertain.json").exists())
        old = CURRENT.read_bytes()
        new = proposed.read_bytes()
        oldmod = load(CURRENT, "old")
        newmod = load(proposed, "new")
        delta(oldmod, newmod)
        changed = old != new
        context = {
            "tool": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "before": hashlib.sha256(old).hexdigest(),
            "after": hashlib.sha256(new).hexdigest(),
            "name": "kuma.socrat",
        }
        digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
        if a.apply and changed:
            require("Fresh hash approval required", ok=a.approve_plan_hash == digest)
            (ROOT / "before.py").write_bytes(old)
            (ROOT / "uncertain.json").write_text(json.dumps(context))
            temp = CURRENT.with_name("public_dns_zone.py.public-web.tmp")
            require("Unexpected temporary renderer", ok=not temp.exists())
            temp.write_bytes(new)
            temp.chmod(0o755)
            temp.replace(CURRENT)
            subprocess.run(
                ["systemctl", "start", "public-dns-refresh.service"],
                check=True,
                capture_output=True,
            )
            result = subprocess.check_output(
                ["knotc", "zone-read", "alchemmist.xyz", "kuma.socrat.alchemmist.xyz.", "A"],
                text=True,
            )
            require(
                "New authoritative record not confirmed",
                ok="A" in result.split()
                and any(ip in result.split() for ip in newmod.healthy_addresses(True, True)),
            )
            (ROOT / "after.json").write_text(
                json.dumps({"renderer_sha256": context["after"], "zone_read_confirmed": True})
            )
            (ROOT / "uncertain.json").unlink()
        print(
            json.dumps(
                {
                    "operations": int(changed),
                    "plan_hash": digest,
                    "applied": bool(a.apply and changed),
                }
            )
        )


if __name__ == "__main__":
    main()
