#!/usr/bin/env python3
"""Add only spi.socrat to the existing authoritative renderer; zone refresh, no restart."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

CURRENT = Path("/usr/local/libexec/public_dns_zone.py")
ROOT = Path("/var/lib/homelab-spi-public-dns")


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def load(path, name):
    require(path.is_file() and not path.is_symlink(), "Unsafe renderer")
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        require(spec is not None and spec.loader is not None, "Invalid renderer module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001 - contain trusted renderer import errors before any DNS write
        raise RuntimeError("Invalid DNS renderer: " + path.name) from None


def delta(old, new):
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        before = old.render(123, home, vps).splitlines()
        after = new.render(123, home, vps).splitlines()
        require(
            [x for x in after if not x.startswith("spi.socrat IN A ")]
            == [x for x in before if not x.startswith("spi.socrat IN A ")],
            "Unrelated DNS record change; stop",
        )
        require(
            [x for x in after if x.startswith("spi.socrat IN A ")]
            == ["spi.socrat IN A " + a for a in old.healthy_addresses(home, vps)],
            "Wrong new record",
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    os.umask(0o077)
    require(
        ROOT.is_dir()
        and not ROOT.is_symlink()
        and ROOT.stat().st_uid == 0
        and not ROOT.stat().st_mode & 0o077,
        "Unsafe state directory",
    )
    proposed = ROOT / "proposed.py"
    for path in [CURRENT, proposed]:
        require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_uid == 0
            and not path.stat().st_mode & 0o022,
            "Unsafe renderer",
        )
    with (ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        require(not (ROOT / "uncertain.json").exists(), "Uncertain prior write; stop")
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
            "name": "spi.socrat",
        }
        digest = hashlib.sha256(
            json.dumps(context, sort_keys=True).encode()
        ).hexdigest()
        if a.apply and changed:
            require(a.approve_plan_hash == digest, "Fresh hash approval required")
            (ROOT / "before.py").write_bytes(old)
            (ROOT / "uncertain.json").write_text(json.dumps(context))
            temp = CURRENT.with_name("public_dns_zone.py.spi-public.tmp")
            require(not temp.exists(), "Unexpected temporary renderer")
            temp.write_bytes(new)
            temp.chmod(0o755)
            temp.replace(CURRENT)
            subprocess.run(
                ["systemctl", "start", "public-dns-refresh.service"],
                check=True,
                capture_output=True,
            )
            result = subprocess.check_output(
                [
                    "knotc",
                    "zone-read",
                    "alchemmist.xyz",
                    "spi.socrat.alchemmist.xyz.",
                    "A",
                ],
                text=True,
            )
            require(
                "A" in result.split()
                and any(
                    ip in result.split() for ip in newmod.healthy_addresses(True, True)
                ),
                "New authoritative record not confirmed",
            )
            (ROOT / "after.json").write_text(
                json.dumps(
                    {"renderer_sha256": context["after"], "zone_read_confirmed": True}
                )
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
    try:
        main()
    except RuntimeError as error:
        raise SystemExit("STOP: " + str(error)) from None
