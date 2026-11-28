#!/usr/bin/env python3
"""One-time CAS admission after source-scoped guard. Never blindly replay.

Existing private config/runtime snapshot stays root-only; stdout is sanitized.
"""

import hashlib
import json
import os
import pathlib
import subprocess
import time

KEY = "kq9Kb6ZF9j/cuBooG3onvLfnBBjI0cTdQK26nKR4R0E="
IP = "10.250.0.41/32"
EXPECTED = "ea9e5dc22fabfe13af8e65fae5944846f8ac11d1d69eb62dc6b301cfbde3d503"
HOST = "socrat-4"
INTERFACE_KEY = "rOXEc8nrYHuYG0D5t+LwY9jxv05zsjxt0P2scF+Sf0k="
PEER_BLOCK = (
    "\n\n[Peer]\n"
    "# bootstrap-only: socrat-5; isolation owned by dedicated guard service\n"
    "PublicKey = " + KEY + "\nAllowedIPs = " + IP + "\n"
    "PersistentKeepalive = 25\n"
)


def run(*args: str) -> str:
    """Run one reviewed command and return its stripped stdout."""
    return subprocess.check_output(args, text=True).strip()


def peers() -> dict[str, str]:
    """Return the current wg-socrat peer map keyed by public key."""
    return dict(
        x.split("\t", 1) for x in run("wg", "show", "wg-socrat", "allowed-ips").splitlines()
    )


def _verify_host_and_guard() -> None:
    """Require the reviewed host, interface key and an active source-scoped guard."""
    if run("hostname") != HOST:
        msg = "Admission must only run on socrat-4"
        raise RuntimeError(msg)
    interface_key = run("wg", "show", "wg-socrat", "public-key")
    if interface_key != INTERFACE_KEY:
        msg = "WireGuard interface key rotated; stop"
        raise RuntimeError(msg)
    if run("systemctl", "is-active", "testing-class-wg-guard.service") != "active":
        msg = "Source-scoped guard service must be active before admission"
        raise RuntimeError(msg)
    subprocess.run(["/usr/local/libexec/testing-class-wg-guard"], check=True)


def _verify_not_yet_admitted(original: dict[str, str]) -> None:
    """Require the reviewed peer and IP to be absent before admission."""
    if KEY in original:
        msg = "Peer must not already be admitted"
        raise RuntimeError(msg)
    if any("10.250.0.41" in x for x in original.values()):
        msg = "Testing-class IP must not be routed to another peer"
        raise RuntimeError(msg)


def _prepare_candidate(conf: pathlib.Path, candidate: bytes) -> pathlib.Path:
    """Archive any old candidate and write the reviewed new candidate file."""
    tmp = conf.with_name("wg-s5-new.conf")
    if tmp.exists():
        msg = "Candidate file must not pre-exist"
        raise RuntimeError(msg)
    old_candidate = conf.with_name("wg-socrat.testing-class-candidate.conf")
    if old_candidate.exists():
        if old_candidate.read_bytes() != candidate:
            msg = "STOP unknown old candidate"
            raise RuntimeError(msg)
        archived = pathlib.Path(
            "/var/lib/homelab-recovery/20261110-testing-class-bootstrap/rejected-long-name.conf"
        )
        if archived.exists():
            msg = "Recovery slot must be empty for the rejected candidate"
            raise RuntimeError(msg)
        old_candidate.replace(archived)
    with tmp.open("xb") as out:
        out.write(candidate)
        out.flush()
        os.fsync(out.fileno())
    return tmp


def _persist_candidate(
    receipts: pathlib.Path,
    conf: pathlib.Path,
    tmp: pathlib.Path,
    before: bytes,
    original: dict[str, str],
    candidate: bytes,
) -> None:
    """Strip-check the unchanged state, record the receipt, then persist atomically."""
    subprocess.run(["wg-quick", "strip", str(tmp)], check=True, stdout=subprocess.DEVNULL)
    if conf.read_bytes() != before:
        msg = "STOP pre-write state changed"
        raise RuntimeError(msg)
    if peers() != original:
        msg = "STOP pre-write state changed"
        raise RuntimeError(msg)
    (receipts / "receipt.json").write_text(
        json.dumps(
            {
                "phase": "prepared",
                "before_sha256": EXPECTED,
                "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
            }
        )
    )
    tmp.replace(conf)
    fd = os.open(str(conf.parent), os.O_RDONLY)
    os.fsync(fd)
    os.close(fd)


def _verify_admission(original: dict[str, str], conf: pathlib.Path, candidate: bytes) -> None:
    """Verify the admitted peer, the untouched peers and the persistent config."""
    current = peers()
    if current.pop(KEY) != IP:
        msg = "Admitted peer must use the reviewed allowed IP"
        raise RuntimeError(msg)
    if current != original:
        msg = "Other peers must stay unchanged"
        raise RuntimeError(msg)
    if conf.read_bytes() != candidate:
        msg = "Persistent config must equal the prepared candidate"
        raise RuntimeError(msg)


def main() -> None:
    """Perform the one-time reviewed CAS peer admission."""
    os.umask(0o077)
    _verify_host_and_guard()
    conf = pathlib.Path("/etc/wireguard/wg-socrat.conf")
    before = conf.read_bytes()
    if hashlib.sha256(before).hexdigest() != EXPECTED:
        msg = "STOP persistent CAS mismatch; inspect receipt, do not replay"
        raise RuntimeError(msg)
    if KEY.encode() in before:
        msg = "Admission key must not be persistent yet"
        raise RuntimeError(msg)
    if b"SaveConfig" in before:
        msg = "Persistent config must not save runtime state"
        raise RuntimeError(msg)
    original = peers()
    _verify_not_yet_admitted(original)
    root = pathlib.Path("/var/lib/homelab-recovery/20261110-socrat5-bootstrap")
    root.mkdir(mode=0o700, exist_ok=False)
    (root / "wg-socrat.before.conf").write_bytes(before)
    (root / "wg-runtime.before.conf").write_text(run("wg", "showconf", "wg-socrat") + "\n")
    candidate = before.rstrip() + PEER_BLOCK.encode()
    tmp = _prepare_candidate(conf, candidate)
    _persist_candidate(root, conf, tmp, before, original, candidate)
    # Surgical one-peer addition: never sync/replace the other peers or restart WG.
    subprocess.run(
        [
            "wg",
            "set",
            "wg-socrat",
            "peer",
            KEY,
            "allowed-ips",
            IP,
            "persistent-keepalive",
            "25",
        ],
        check=True,
    )
    _verify_admission(original, conf, candidate)
    result = {
        "phase": "peer-admitted-awaiting-client",
        "address": IP,
        "other_peer_allowed_ips_preserved": True,
        "wg_service": run("systemctl", "is-active", "wg-quick@wg-socrat"),
        "persistent_sha256": hashlib.sha256(candidate).hexdigest(),
        "at": time.time(),
    }
    (root / "receipt.json").write_text(json.dumps(result))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
