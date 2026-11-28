#!/usr/bin/env python3
"""Plan by default; --apply needs native macOS root consent. Exact control DNS only."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

PREEXISTING_MAX_BYTES = 4096
HOSTS = (
    "netbird.socrat.alchemmist.xyz",
    "netbird-relay-vps.socrat.alchemmist.xyz",
    "auth.socrat.alchemmist.xyz",
)
PUBLIC_DNS = ("1.1.1.1", "9.9.9.9")


def render() -> bytes:
    """Return the reviewed public resolver file body for NetBird bootstrap."""
    return (
        "# NetBird/Auth bootstrap must not depend on the private VPN DNS path.\n"
        + "".join("nameserver " + ip + "\n" for ip in PUBLIC_DNS)
        + "timeout 2\noptions attempts:2\n"
    ).encode()


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


def _back_up_host_resolver(p: Path, host: str, backup: Path) -> bytes | None:
    """Back up any pre-existing host resolver and return its bytes (None if absent)."""
    if not p.exists():
        return None
    if not p.is_file():
        msg = "Existing resolver for " + host + " is not a regular file"
        raise RuntimeError(msg)
    old = p.read_bytes()
    if len(old) >= PREEXISTING_MAX_BYTES:
        msg = "Existing resolver for " + host + " is unexpectedly large"
        raise RuntimeError(msg)
    fd = os.open(backup / (host + ".before"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(old)
    return old


def _write_host_resolver_atomically(folder: Path, p: Path, body: bytes) -> None:
    """Write one rendered resolver beside the target and rename it into place."""
    fd, tmp = tempfile.mkstemp(prefix=".netbird-bootstrap-", dir=folder)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        tmp_path = Path(tmp)
        tmp_path.replace(p)
    finally:
        tmp_path = Path(tmp)
        if tmp_path.exists():
            tmp_path.unlink()


def apply() -> None:
    """Install the rendered resolver file under explicit macOS root authorization."""
    if sys.platform != "darwin" or os.geteuid() != 0:
        msg = "Explicit macOS root authorization required"
        raise RuntimeError(msg)
    folder = _require_resolver_folder()
    backup = Path("/var/root/.local/state/netbird-bootstrap-dns")
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (backup / "complete.json").exists():
        msg = "existing completed change: stop, inspect"
        raise RuntimeError(msg)
    body = render()
    result: dict[str, object] = {}
    for host in HOSTS:
        p = folder / host
        if p.is_symlink():
            msg = "Existing resolver for " + host + " is a symlink"
            raise RuntimeError(msg)
        old = _back_up_host_resolver(p, host, backup)
        if old is not None:
            result[host] = {
                "preexisting": True,
                "before_sha256": hashlib.sha256(old).hexdigest(),
            }
        else:
            result[host] = {"preexisting": False}
        _write_host_resolver_atomically(folder, p, body)
        entry = cast("dict[str, object]", result[host])
        entry["after_sha256"] = hashlib.sha256(body).hexdigest()
    fd = os.open(backup / "complete.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(result, f)
    subprocess.run(["/usr/bin/dscacheutil", "-flushcache"], check=True)
    subprocess.run(["/usr/bin/killall", "-HUP", "mDNSResponder"], check=True)
    print(
        "Three exact control-plane DNS exceptions installed; "
        "private app resolvers unchanged; root-only backups saved."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        apply()
    else:
        print(
            json.dumps(
                {
                    "apply": False,
                    "exact_control_domains": HOSTS,
                    "public_dns": PUBLIC_DNS,
                    "private_app_dns_unchanged": True,
                },
                indent=2,
            )
        )
