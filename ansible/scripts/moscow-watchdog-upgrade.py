#!/usr/bin/env python3
"""Install an exact reviewed controller only while healthy fenced native owns VPN."""

import argparse
import ast
import fcntl
import hashlib
import json
import os
import pathlib
import subprocess
import time

DEST = pathlib.Path("/usr/local/libexec/vpn-transit-failover.py")
STATE = pathlib.Path("/var/lib/homelab-vpn-transit/relay-failover")
ROOT = pathlib.Path("/var/lib/homelab-recovery/20261113-moscow-watchdog-repair")
OLD = "81fa706264d5d9f5b86f3b7423fc1e9bf3324e955e57594297b1ad25edad35be"


def sha(data) -> str:
    return hashlib.sha256(data).hexdigest()


def unit(name) -> bool:
    return subprocess.run(["systemctl", "is-active", "--quiet", name], timeout=5).returncode == 0


def install(candidate, expected) -> None:
    if os.geteuid() != 0 or os.uname().nodename != "socrat-4":
        msg = "Wrong privilege or host"
        raise RuntimeError(msg)
    data = candidate.read_bytes()
    ast.parse(data)
    if sha(data) != expected:
        msg = "Unreviewed candidate SHA"
        raise RuntimeError(msg)
    with (STATE / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        old = DEST.read_bytes()
        if DEST.is_symlink() or sha(old) != OLD:
            msg = "Controller drift or prior attempt"
            raise RuntimeError(msg)
        state = json.loads((STATE / "state.json").read_text())
        if (
            state["mode"] != "native"
            or not state.get("healthy")
            or not (STATE / "fallback.active").is_file()
        ):
            msg = "Expected healthy fenced native"
            raise RuntimeError(msg)
        if not unit("homelab-vpn-transit-native") or unit("k3s-agent"):
            msg = "Runtime ownership conflict"
            raise RuntimeError(msg)
        if ROOT.exists():
            msg = "Prior upgrade attempt; inspect, do not replay"
            raise RuntimeError(msg)
        ROOT.mkdir(mode=0o700, parents=True)
        for path, payload in [
            (ROOT / "before.py", old),
            (
                ROOT / "intent.json",
                json.dumps({"old": OLD, "new": expected, "at": time.time()}).encode(),
            ),
        ]:
            with path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(path, 0o600)
        fd = os.open(ROOT, os.O_DIRECTORY)
        os.fsync(fd)
        os.close(fd)
        temp = DEST.with_name(DEST.name + ".repair-tmp")
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o700)
        os.replace(temp, DEST)
        fd = os.open(DEST.parent, os.O_DIRECTORY)
        os.fsync(fd)
        os.close(fd)
        if sha(DEST.read_bytes()) != expected:
            msg = "Postcondition drift"
            raise RuntimeError(msg)
        accepted = {"installed": expected, "runtime_changed": False}
        with (ROOT / "accepted.json").open("x") as stream:
            json.dump(accepted, stream)
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(ROOT, os.O_DIRECTORY)
        os.fsync(fd)
        os.close(fd)
        print(json.dumps(accepted))


if __name__ == "__main__":
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument("--candidate", type=pathlib.Path, required=True)
    p.add_argument("--sha256", required=True)
    args = p.parse_args()
    install(args.candidate, args.sha256)
