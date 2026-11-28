#!/usr/bin/env python3
"""Exact macOS n8n public DNS exception; plan by default, native root consent to apply."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PREEXISTING_MAX_BYTES = 4096
HOST = "n8n.socrat.alchemmist.xyz"
BODY = (
    b"# Public n8n HTTPS must not depend on private VPN DNS. Authentik remains required."
    b"\nnameserver 1.1.1.1"
    b"\nnameserver 9.9.9.9"
    b"\ntimeout 2"
    b"\noptions attempts:2"
    b"\n"
)


def _require_resolver_folder() -> Path:
    """Require the reviewed native macOS resolver folder shape."""
    folder = Path("/etc/resolver")
    if not folder.is_dir():
        msg = "Native macOS resolver folder missing"
        raise RuntimeError(msg)
    if folder.is_symlink():
        msg = "Resolver folder must not be a symlink"
        raise RuntimeError(msg)
    if folder.stat().st_uid != 0:
        msg = "Resolver folder must be owned by root"
        raise RuntimeError(msg)
    if folder.stat().st_mode & 0o022:
        msg = "Resolver folder must stay group/world non-writable"
        raise RuntimeError(msg)
    return folder


def _require_preserved_shape(p: Path, old: bytes | None) -> None:
    """Require any pre-existing n8n resolver to be a small regular file."""
    if old is None:
        return
    if not p.is_file():
        msg = "Existing n8n resolver is not a regular file"
        raise RuntimeError(msg)
    if len(old) >= PREEXISTING_MAX_BYTES:
        msg = "Existing n8n resolver is unexpectedly large"
        raise RuntimeError(msg)


def _write_resolver_atomically(folder: Path, p: Path, old: bytes | None) -> None:
    """Write the new resolver beside the target and rename it after re-verify."""
    fd, tmp = tempfile.mkstemp(prefix=".n8n-public-", dir=folder)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(BODY)
            f.flush()
            os.fsync(f.fileno())
        tmp_path = Path(tmp)
        if p.is_symlink():
            msg = "Concurrent change: stop"
            raise RuntimeError(msg)
        if (p.read_bytes() if p.exists() else None) != old:
            msg = "Concurrent change: stop"
            raise RuntimeError(msg)
        tmp_path.replace(p)
    finally:
        tmp_path = Path(tmp)
        if tmp_path.exists():
            tmp_path.unlink()


def apply() -> None:
    """Install the reviewed public n8n resolver file after backing up any previous one."""
    if sys.platform != "darwin" or os.geteuid() != 0:
        msg = "Native macOS administrator authorization required"
        raise RuntimeError(msg)
    folder = _require_resolver_folder()
    p = folder / HOST
    if p.is_symlink():
        msg = "Existing n8n resolver is a symlink"
        raise RuntimeError(msg)
    old = p.read_bytes() if p.exists() else None
    if old == BODY:
        print("Exact public n8n resolver already installed")
        return
    _require_preserved_shape(p, old)
    backup = Path("/var/root/.local/state/n8n-public-dns") / str(time.time_ns())
    backup.mkdir(parents=True, mode=0o700)
    if old is not None:
        (backup / "resolver.before").write_bytes(old)
        (backup / "resolver.before").chmod(0o600)
    (backup / "metadata.json").write_text(
        json.dumps(
            {
                "path": str(p),
                "preexisting": old is not None,
                "before_sha256": hashlib.sha256(old).hexdigest() if old is not None else None,
                "after_sha256": hashlib.sha256(BODY).hexdigest(),
            }
        )
    )
    (backup / "metadata.json").chmod(0o600)
    _write_resolver_atomically(folder, p, old)
    subprocess.run(["/usr/bin/dscacheutil", "-flushcache"], check=True)
    subprocess.run(["/usr/bin/killall", "-HUP", "mDNSResponder"], check=True)
    print("Only n8n resolver changed; root-only backup: " + str(backup))


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--apply", action="store_true")
    args = a.parse_args()
    if args.apply:
        apply()
    else:
        print(
            json.dumps(
                {
                    "apply": False,
                    "exact_domain": HOST,
                    "resolver": BODY.decode(),
                    "other_domains_unchanged": True,
                },
                indent=2,
            )
        )
