#!/usr/bin/env python3
"""Explicit one-shot atomic exchange of verified dormant native image on NL.

Never stops/starts any service. The watchdog lock protects the standby path while
Kubernetes continues serving the SAME live DB. Old image retained in candidate.
"""

import argparse
import ctypes
import fcntl
import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path("/opt/homelab-vpn-failover")
STATE = Path("/var/lib/homelab-vpn-failover")
RECEIPT = Path("/var/lib/homelab-recovery/20261113-vpn-native-image/promotion.json")
SMOKE_MAX_AGE_SECONDS = 900


def active(unit: str) -> bool:
    """Check whether a systemd unit reports the active state."""
    p = subprocess.run(
        ["systemctl", "is-active", "--quiet", unit],
        check=False,
        capture_output=True,
        timeout=5,
    )
    if p.returncode not in (0, 3):
        msg = "is-active returned an unexpected status"
        raise RuntimeError(msg)
    return p.returncode == 0


def running_core() -> str:
    """Hash the live xray core binary of the running native instance."""
    found: list[Path] = []
    for path in Path("/proc").glob("[0-9]*/exe"):
        try:
            if path.readlink().name != "xray-linux-amd64":
                continue
            if any(
                x.endswith(b"bin/config.json")
                for x in (path.parent / "cmdline").read_bytes().split(b"\0")
            ):
                found.append(path)
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    if len(found) != 1:
        msg = "Exactly one running native xray core is required"
        raise RuntimeError(msg)
    return hashlib.sha256(found[0].read_bytes()).hexdigest()


def promote(candidate: Path, old_image: str, new_image: str) -> None:
    """Atomically exchange the verified dormant image, stopping on any doubt."""
    if os.geteuid() != 0:
        msg = "Promotion must run as root"
        raise RuntimeError(msg)
    if socket.gethostname() != "socrat-2":
        msg = "Promotion must run on the NL host"
        raise RuntimeError(msg)
    if candidate.parent != ROOT:
        msg = "Candidate must live directly beneath the promotion root"
        raise RuntimeError(msg)
    if not candidate.name.startswith("staged-"):
        msg = "Candidate must use the staged- directory prefix"
        raise RuntimeError(msg)
    if candidate.is_symlink():
        msg = "Candidate must be a real directory, never a symlink"
        raise RuntimeError(msg)
    if RECEIPT.exists():
        msg = "Existing attempt/receipt; inspect, never replay"
        raise RuntimeError(msg)
    proof = json.loads((candidate / ".isolated-smoke-accepted.json").read_text())
    if not proof["healthy"]:
        msg = "Recorded isolated smoke must be healthy"
        raise RuntimeError(msg)
    if not proof["cleanup_verified"]:
        msg = "Recorded isolated smoke cleanup must be verified"
        raise RuntimeError(msg)
    if proof["production_runtime_changed"]:
        msg = "Isolated smoke must not have changed the production runtime"
        raise RuntimeError(msg)
    if not 0 <= time.time() - proof["accepted_at"] <= SMOKE_MAX_AGE_SECONDS:
        msg = "Fresh isolated smoke required"
        raise RuntimeError(msg)
    if proof["image"] != new_image:
        msg = "Smoke receipt must pin the requested new image"
        raise RuntimeError(msg)
    new = candidate / "primary"
    current = ROOT / "primary"
    if new.is_symlink() or current.is_symlink():
        msg = "Neither image directory may be a symlink"
        raise RuntimeError(msg)
    if new.stat().st_dev != current.stat().st_dev:
        msg = "Images must share one filesystem for the atomic exchange"
        raise RuntimeError(msg)
    if (new / ".homelab-image").read_text().strip() != new_image:
        msg = "Candidate primary must carry the new image label"
        raise RuntimeError(msg)
    if hashlib.sha256((new / "app/x-ui").read_bytes()).hexdigest() != proof["ui_sha256"]:
        msg = "Candidate x-ui binary must match the smoke receipt hash"
        raise RuntimeError(msg)
    core = hashlib.sha256((new / "app/bin/xray-linux-amd64").read_bytes()).hexdigest()
    if core != running_core():
        msg = "Candidate core differs from live; stop for explicit review"
        raise RuntimeError(msg)
    with (STATE / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (STATE / "active").exists():
            msg = "Failover state must not be active"
            raise RuntimeError(msg)
        if (STATE / "inhibit").exists():
            msg = "Promotion is inhibited"
            raise RuntimeError(msg)
        if not active("k3s.service"):
            msg = "Kubernetes must stay active during the exchange"
            raise RuntimeError(msg)
        if active("homelab-vpn-primary.service"):
            msg = "Native primary service must be dormant"
            raise RuntimeError(msg)
        if active("homelab-vpn-caddy.service"):
            msg = "Native caddy service must be dormant"
            raise RuntimeError(msg)
        status = subprocess.run(
            ["/usr/local/sbin/homelab-vpn-failover", "status"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if status.returncode != 0:
            msg = "Failover status probe failed"
            raise RuntimeError(msg)
        if not json.loads(status.stdout)["healthy"]:
            msg = "Failover watchdog must report health"
            raise RuntimeError(msg)
        if (current / ".homelab-image").read_text().strip() != old_image:
            msg = "Live image label must still match the recorded old image"
            raise RuntimeError(msg)
        # Durable intent before atomic syscall; any uncertainty prohibits replay.
        fd = os.open(RECEIPT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(
                {"state": "intent", "old_image": old_image, "new_image": new_image},
                stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(RECEIPT.parent, os.O_DIRECTORY)
        os.fsync(fd)
        os.close(fd)
        libc = ctypes.CDLL(None, use_errno=True)
        fn = libc.renameat2
        fn.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        if fn(-100, os.fsencode(current), -100, os.fsencode(new), 2) != 0:
            raise OSError(ctypes.get_errno(), "Atomic image exchange failed; inspect intent")
        for path in (ROOT, candidate):
            fd = os.open(path, os.O_DIRECTORY)
            os.fsync(fd)
            os.close(fd)
        if (current / ".homelab-image").read_text().strip() != new_image:
            msg = "Atomic exchange must leave the new image live"
            raise RuntimeError(msg)
        if (new / ".homelab-image").read_text().strip() != old_image:
            msg = "Atomic exchange must preserve the old image in the candidate"
            raise RuntimeError(msg)
        receipt = {
            "state": "accepted",
            "old_image_preserved": True,
            "new_image": new_image,
            "core_matches_running": True,
            "no_runtime_restart": True,
            "at": time.time(),
        }
        temporary = RECEIPT.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(receipt, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(RECEIPT)
        fd = os.open(RECEIPT.parent, os.O_DIRECTORY)
        os.fsync(fd)
        os.close(fd)
        print(json.dumps(receipt))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--old-image", required=True)
    p.add_argument("--new-image", required=True)
    a = p.parse_args()
    try:
        promote(a.candidate, a.old_image, a.new_image)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        msg = "Native image promotion stopped; inspect private intent/receipts, never replay."
        raise SystemExit(msg) from None
