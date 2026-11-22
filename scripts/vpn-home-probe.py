#!/usr/bin/env python3
"""Owned, per-process home fixed-path VPN acceptance. No OS proxy/routes/DNS writes.

Takes private prepared configs and a checksum-pinned copy of the running Xray core.
Only temporary loopback SOCKS proxies and a single64KiB request per protocol.
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import cast


def exclusive(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())


def network(endpoint="91.189.82.238"):
    r = subprocess.run(
        ["ip", "-j", "route", "get", endpoint],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode:
        raise ValueError("Route read failed")
    rows = json.loads(r.stdout)
    if len(rows) != 1 or rows[0].get("dev") != "eno1" or rows[0].get("gateway") != "192.168.0.1":
        raise ValueError("Not approved home WAN route")
    main = subprocess.run(
        ["ip", "-j", "route", "show", "table", "main"],
        check=False,
        capture_output=True,
        timeout=10,
    )
    if main.returncode:
        raise ValueError("Route snapshot failed")
    return {
        "route_device": "eno1",
        "gateway": "192.168.0.1",
        "main_route_sha256": hashlib.sha256(main.stdout).hexdigest(),
        "resolv_conf_sha256": hashlib.sha256(Path("/etc/resolv.conf").read_bytes()).hexdigest(),
    }


def require_global_endpoint(endpoint: str) -> None:
    """Refuse private or otherwise non-global probe endpoints."""
    import ipaddress

    if not ipaddress.ip_address(endpoint).is_global:
        raise ValueError("Public probe endpoint required")


def require_home_host() -> None:
    """Refuse any host other than the pinned home controller running as root."""
    if socket.gethostname() != "socrat-0" or os.geteuid() != 0:
        raise ValueError("Requires socrat-0 root")


def require_private_state(state: Path) -> None:
    """Refuse symlinked or non-root-writable state directories."""
    if (
        state.is_symlink()
        or any(p.is_symlink() for p in state.parents)
        or state.stat().st_mode & 0o077
        or state.stat().st_uid != 0
    ):
        raise ValueError("Private state required")


def require_pinned_runtime(state: Path, approved_binary: str) -> tuple[Path, Path]:
    """Refuse unpinned binaries or symlinked configs; return both paths."""
    binary = state / "xray-probe"
    configs = state / "home-configs-private.json"
    if binary.is_symlink() or configs.is_symlink():
        raise ValueError("Symlink refused")
    if hashlib.sha256(binary.read_bytes()).hexdigest() != approved_binary:
        raise ValueError("Binary checksum mismatch")
    return binary, configs


def require_literal_endpoints(prepared: dict[str, dict[str, object]], endpoint: str) -> None:
    """Refuse prepared configs that do not dial the literal approved VPS IP."""
    reality = prepared["reality"]
    trojan = prepared["trojan"]
    reality_outbounds = cast("list[dict[str, object]]", reality["outbounds"])
    trojan_outbounds = cast("list[dict[str, object]]", trojan["outbounds"])
    reality_vnext = cast(
        "list[dict[str, object]]",
        cast("dict[str, object]", reality_outbounds[1]["settings"])["vnext"],
    )
    trojan_servers = cast(
        "list[dict[str, object]]",
        cast("dict[str, object]", trojan_outbounds[1]["settings"])["servers"],
    )
    if (
        cast("str", reality_vnext[0]["address"]) != endpoint
        or cast("str", trojan_servers[0]["address"]) != endpoint
    ):
        raise ValueError("Both protocols must use literal approved VPS IP")


def add_ipify_rule(config: dict[str, object]) -> None:
    """Extend an existing full:speed.cloudflare.com rule with the probe domain."""
    routing = cast("dict[str, object]", config.get("routing", {}))
    for rule in cast("list[dict[str, object]]", routing.get("rules", [])):
        domains = cast("list[str]", rule.get("domain", []))
        if "full:speed.cloudflare.com" in domains:
            domains.append("full:api4.ipify.org")


def reserve_port() -> int:
    """Reserve one ephemeral loopback port for this probe only."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return cast("int", reservation.getsockname()[1])


def wait_listener(process: subprocess.Popen[bytes], port: int) -> None:
    """Wait for the local SOCKS listener, failing if the client exits first."""
    for attempt in range(40):
        if process.poll() is not None:
            raise RuntimeError("Own home client exited")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return
        except OSError:
            if attempt == 39:
                raise
            time.sleep(0.25)


def require_nl_egress(port: int) -> None:
    """Prove the tunnel egresses from the pinned Netherlands IPv4 address."""
    egress = subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--max-time",
            "20",
            "--max-filesize",
            "64",
            "--proxy",
            "socks5h://127.0.0.1:" + str(port),
            "https://api4.ipify.org",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=25,
        env=dict(os.environ, NO_PROXY="", no_proxy=""),
    )
    if egress.returncode or egress.stdout.strip() != "109.120.141.60":
        raise RuntimeError("Expected Netherlands IPv4 egress not proven")


def transfer_and_verify(state: Path, label: str, port: int) -> dict[str, object]:
    """Fetch one 64KiB proof body through the tunnel and hash it."""
    body = state / (label + "-body.bin")
    args = [
        "curl",
        "--silent",
        "--show-error",
        "--max-time",
        "30",
        "--max-filesize",
        "131072",
        "--proxy",
        "socks5h://127.0.0.1:" + str(port),
        "--output",
        str(body),
        "--write-out",
        "%{http_code} %{size_download}",
        "https://speed.cloudflare.com/__down?bytes=65536",
    ]
    r = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=35,
        env=dict(os.environ, NO_PROXY="", no_proxy=""),
    )
    exclusive(
        state / (label + "-curl-private.json"),
        {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr},
    )
    if r.returncode or r.stdout.strip() != "200 65536" or body.stat().st_size != 65536:
        raise RuntimeError("Home tunnel transfer failed")
    proof: dict[str, object] = {
        "http_status": 200,
        "bytes": 65536,
        "sha256": hashlib.sha256(body.read_bytes()).hexdigest(),
        "egress_ipv4": "109.120.141.60",
    }
    body.unlink()
    return proof


def probe_label(
    state: Path,
    label: str,
    config: dict[str, object],
    binary: Path,
) -> dict[str, object]:
    """Run one prepared protocol config on its own port and return the proof."""
    add_ipify_rule(config)
    port = reserve_port()
    cast("list[dict[str, object]]", config["inbounds"])[0]["port"] = port
    path = state / (label + "-config-private.json")
    exclusive(path, config)
    logpath = state / (label + "-log-private.txt")
    fd = os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as log:
        process = subprocess.Popen(
            [str(binary), "run", "-c", str(path)], stdout=log, stderr=subprocess.STDOUT
        )
        try:
            wait_listener(process, port)
            require_nl_egress(port)
            return transfer_and_verify(state, label, port)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            path.unlink(missing_ok=True)


def run(state, approved_binary, endpoint="91.189.82.238"):
    require_global_endpoint(endpoint)
    require_home_host()
    require_private_state(state)
    binary, configs = require_pinned_runtime(state, approved_binary)
    prepared = json.loads(configs.read_text())
    before = network(endpoint)
    proofs = {}
    require_literal_endpoints(prepared, endpoint)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("https://api.ipify.org", timeout=10) as r:
            public = r.read(64).decode().strip()
        exclusive(state / "source-address-private.json", {"actual_public_ip": public})
        expected_home_source = public == "109.173.40.247"
        for label in prepared:
            proofs[label] = probe_label(state, label, prepared[label], binary)
        after = network(endpoint)
        if before != after:
            raise ValueError("Network state changed during home probe")
        result = {
            "vantage": "home-fixed-WAN-not-mobile",
            "expected_home_public_source": expected_home_source,
            "uses_overlay_to_vps": False,
            "literal_endpoint": endpoint,
            "network_state_preserved": True,
            "own_ephemeral_identity_only": True,
            "protocols": proofs,
            "reality": proofs["reality"],
            "trojan": proofs["trojan"],
            "mobile_acceptance": False,
        }
        exclusive(state / "receipt.json", result)
        return result
    finally:
        configs.unlink(missing_ok=True)
        binary.unlink(missing_ok=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--approved-binary-sha256", required=True)
    p.add_argument("--endpoint", default="91.189.82.238")
    a = p.parse_args()
    try:
        print(json.dumps(run(a.state, a.approved_binary_sha256, endpoint=a.endpoint)))
    except Exception:
        raise SystemExit(
            "Home probe stopped; inspect private evidence; no global network changes requested."
        ) from None
