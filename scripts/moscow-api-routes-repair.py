#!/usr/bin/env python3
"""One-shot additive repair, no WG/interface/service restart or key mutation."""

import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
import pathlib
import socket
import subprocess

CONFIG = pathlib.Path("/etc/wireguard/wg-socrat.conf")
ROOT = pathlib.Path("/var/lib/homelab-recovery/20261113-moscow-api-routes")
PEERS = {
    "V5a15CeZ//mVOdddiIGRI/CLDny6a1r22loXLMcQxkU=": "192.168.0.23/32",
    "b2yWaBu06tk67Tx1N1SUktl0DntkcnKU36tIKLiqM0c=": "192.168.0.24/32",
}


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=10).stdout


def allowed_ips(text):
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] in result:
            raise ValueError("Duplicate runtime peer")
        result[fields[0]] = [value for token in fields[1:] for value in token.split(",") if value]
    return result


def project(text):
    blocks = []
    current = []
    for line in text.splitlines(keepends=True):
        if line.strip().startswith("[") and current:
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    parsed = {}
    for block in blocks:
        if not any(line.strip() == "[Peer]" for line in block):
            continue
        fields = {
            line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
            for line in block
            if "=" in line and not line.lstrip().startswith(("#", ";"))
        }
        key = fields["PublicKey"]
        if key in parsed:
            raise ValueError("Duplicate peer")
        parsed[key] = [x.strip() for x in fields["AllowedIPs"].split(",")]
    return blocks, parsed


def _confirm_no_overlap(peers: dict[str, list[str]]) -> None:
    """Refuse any overlap between pinned HOME routes and other peers."""
    for key, networks in peers.items():
        for network in networks:
            for owner, target in PEERS.items():
                if key != owner and ipaddress.ip_network(target).overlaps(
                    ipaddress.ip_network(network, strict=False)
                ):
                    raise ValueError("API address owned by another peer")


def _render_config(blocks: list[list[str]], after: dict[str, list[str]]) -> str:
    """Rewrite each pinned peer's AllowedIPs line with the repaired routes."""
    output = []
    for block in blocks:
        fields = {
            line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
            for line in block
            if "=" in line and not line.lstrip().startswith(("#", ";"))
        }
        key = fields.get("PublicKey")
        for line in block:
            if key in PEERS and line.split("=", 1)[0].strip() == "AllowedIPs":
                line = "AllowedIPs = " + ", ".join(after[key]) + "\n"
            output.append(line)
    return "".join(output)


def candidate(text, runtime):
    blocks, peers = project(text)
    if peers != runtime:
        raise ValueError("Boot/runtime AllowedIPs drift")
    if not set(PEERS) <= set(peers):
        raise ValueError("Missing pinned HOME peer")
    _confirm_no_overlap(peers)
    after = {k: list(v) for k, v in peers.items()}
    for key, target in PEERS.items():
        if target not in after[key]:
            after[key].append(target)
    return _render_config(blocks, after), after


def atomic(path, data):
    temp = path.with_name(path.name + ".repair-tmp")
    with temp.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    os.fsync(fd)
    os.close(fd)


def _refuse_unsafe_context() -> tuple[bytes, str]:
    """Refuse to run except as root on the designated host with a clean config."""
    if os.geteuid() != 0:
        raise RuntimeError("Root required")
    if os.uname().nodename != "socrat-4":
        raise RuntimeError("Wrong host")
    if CONFIG.is_symlink():
        raise ValueError("Unowned boot config symlink")
    old = CONFIG.read_bytes()
    text = old.decode()
    if any(line.strip().lower() == "saveconfig = true" for line in text.splitlines()):
        raise ValueError("SaveConfig would overwrite reviewed boot state")
    return old, text


def _refuse_existing_routes() -> None:
    """Refuse repair when an explicit route or attempt already exists."""
    routes = {
        target: json.loads(run("ip", "-j", "route", "show", "exact", target))
        for target in PEERS.values()
    }
    for values in routes.values():
        if values:
            raise ValueError("Existing explicit route/attempt; inspect, do not replace")
    # Do not add routes to a peer without checking the existing WG API transport.
    for address in ("10.250.0.1", "10.250.0.3"):
        with socket.create_connection((address, 6443), timeout=3):
            pass


def _stage_intent(old: bytes, new: str, result: dict[str, object]) -> None:
    """Persist the reviewed intent and swap the boot config atomically."""
    if ROOT.exists():
        raise ValueError("Existing recovery attempt; do not replay")
    ROOT.mkdir(parents=True, mode=0o700)
    atomic(ROOT / "intent.json", json.dumps(result).encode())
    atomic(ROOT / "before.conf", old)
    if CONFIG.read_bytes() != old:
        raise ValueError("Concurrent boot config change")
    atomic(CONFIG, new.encode())


def _activate_routes(after: dict[str, list[str]]) -> None:
    """Apply the repaired allowed-ips and add the pinned HOME routes."""
    for key, target in PEERS.items():
        run("wg", "set", "wg-socrat", "peer", key, "allowed-ips", ",".join(after[key]))
        run("ip", "route", "add", target, "dev", "wg-socrat", "src", "10.250.0.40")


def _verify_routes() -> None:
    """Confirm kernel routes and live API reachability through the tunnel."""
    for target in PEERS.values():
        route = json.loads(run("ip", "-j", "route", "get", target.split("/")[0]))[0]
        if route.get("dev") != "wg-socrat" or route.get("prefsrc") != "10.250.0.40":
            raise ValueError("Route verification failed")
        with socket.create_connection((target.split("/")[0], 6443), timeout=3):
            pass


def repair(apply=False):
    old, text = _refuse_unsafe_context()
    runtime = allowed_ips(run("wg", "show", "wg-socrat", "allowed-ips"))
    new, after = candidate(text, runtime)
    _refuse_existing_routes()
    result = {
        "host": "socrat-4",
        "targets": list(PEERS.values()),
        "before_sha256": hashlib.sha256(old).hexdigest(),
        "after_sha256": hashlib.sha256(new.encode()).hexdigest(),
        "apply": apply,
    }
    if not apply:
        return result
    _stage_intent(old, new, result)
    _activate_routes(after)
    _verify_routes()
    expected = allowed_ips(run("wg", "show", "wg-socrat", "allowed-ips"))
    if expected != after or CONFIG.read_text() != new:
        raise ValueError("Postcondition drift")
    result["accepted"] = True
    atomic(ROOT / "accepted.json", json.dumps(result).encode())
    return result


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    # Serialize the complete read/modify/write with the local relay controller.
    with pathlib.Path("/var/lib/homelab-vpn-transit/relay-failover/lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        print(json.dumps(repair(args.apply)))
