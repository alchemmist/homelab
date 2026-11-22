#!/usr/bin/env python3
"""Add only spi.socrat to the existing authoritative renderer; zone refresh, no restart."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import types
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import types

CURRENT = Path("/usr/local/libexec/public_dns_zone.py")
ROOT = Path("/var/lib/homelab-spi-public-dns")


def require(ok, message) -> None:
    if not ok:
        raise RuntimeError(message)


def load(path, name) -> "types.ModuleType":
    require(path.is_file() and not path.is_symlink(), "Unsafe renderer")
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        require(message="Invalid renderer module", ok=spec is not None and spec.loader is not None)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except (OSError, ValueError, RuntimeError, ImportError, SyntaxError):
        raise RuntimeError("Invalid DNS renderer: " + path.name) from None


def stage_renderer(path, content) -> None:
    """Create a new inode exclusively; never follow/overwrite an existing path."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError("Unexpected temporary renderer") from None
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fchmod(stream.fileno(), 0o755)
        os.fsync(stream.fileno())


def delta(old, new) -> None:
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        before = old.render(123, home_up=home, vps_up=vps).splitlines()
        after = new.render(123, home_up=home, vps_up=vps).splitlines()
        require(
            message="Unrelated DNS record change; stop",
            ok=[x for x in after if not x.startswith("spi.socrat IN A ")]
            == [x for x in before if not x.startswith("spi.socrat IN A ")],
        )
        require(
            message="Wrong new record",
            ok=[x for x in after if x.startswith("spi.socrat IN A ")]
            == ["spi.socrat IN A " + a for a in old.healthy_addresses(home_up=home, vps_up=vps)],
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    os.umask(0o077)
    require(
        message="Unsafe state directory",
        ok=ROOT.is_dir()
        and not ROOT.is_symlink()
        and ROOT.stat().st_uid == 0
        and not ROOT.stat().st_mode & 0o077,
    )
    proposed = ROOT / "proposed.py"
    # Public renderer is intentionally 0755; non-owner writes, not reads/exec,
    # violate integrity. importlib does not apply Unix setuid/setgid semantics.
    for path in [CURRENT, proposed]:
        require(
            message="Unsafe renderer",
            ok=path.is_file()
            and not path.is_symlink()
            and path.stat().st_uid == 0
            and not path.stat().st_mode & 0o022,
        )
    with (ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        require(message="Uncertain prior write; stop", ok=not (ROOT / "uncertain.json").exists())
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
        digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
        if a.apply and changed:
            require(message="Fresh hash approval required", ok=a.approve_plan_hash == digest)
            (ROOT / "before.py").write_bytes(old)
            (ROOT / "uncertain.json").write_text(json.dumps(context))
            temp = CURRENT.with_name("public_dns_zone.py.spi-public.tmp")
            stage_renderer(temp, new)
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
                message="New authoritative record not confirmed",
                ok="A" in result.split()
                and any(ip in result.split() for ip in newmod.healthy_addresses(home_up=True, vps_up=True)),
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
    try:
        main()
    except RuntimeError as error:
        raise SystemExit("STOP: " + str(error)) from None
