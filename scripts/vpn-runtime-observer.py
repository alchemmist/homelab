#!/usr/bin/env python3
"""Read-only local VPN runtime/transport observer; NEVER calls tick or failback.

Metrics contain no accounts, credentials, WS paths or command/error output.
A TLS/WS check is not authenticated VPN acceptance. OFF requires absence of ALL
local TCP+UDP data listeners, not one failed protocol or a stale metric.
"""

import argparse
import hashlib
import json
import os
import runpy
import socket
import subprocess
import tempfile
import time
from pathlib import Path

OUTPUT = Path("/var/lib/node_exporter/textfile_collector/vpn-runtime.prom")
PROFILES: dict[str, dict[str, object]] = {
    "socrat-4": {
        "component": "relay",
        "command": ["python3", "/usr/local/libexec/vpn-transit-failover.py", "status"],
        "agent": "k3s-agent.service",
        "native": ["homelab-vpn-transit-native.service"],
        "timer": "homelab-vpn-transit-watchdog.timer",
        "marker": "/var/lib/homelab-vpn-transit/relay-failover/fallback.active",
        "tcp": {443, 32053, 32083, 32084},
        "udp": {443, 32085, 32086},
    },
    "socrat-2": {
        "component": "backend",
        "command": ["/usr/local/sbin/homelab-vpn-failover", "status"],
        "agent": "k3s.service",
        "native": ["homelab-vpn-primary.service", "homelab-vpn-caddy.service"],
        "timer": "homelab-vpn-watchdog.timer",
        "marker": "/var/lib/homelab-vpn-failover/active",
        "tcp": {32053, 32083, 32084, 32087},
        "udp": {32085, 32086},
    },
}


def command(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def active(unit: str) -> bool:
    p = command(["systemctl", "is-active", unit], 5)
    if p.returncode not in (0, 3):
        raise ValueError("Unobservable unit")
    return p.returncode == 0


def _unit_list(value: object) -> list[str]:
    items = value if isinstance(value, list) else []
    return [str(u) for u in items]


def _port_set(value: object) -> set[int]:
    items = value if isinstance(value, list) else []
    return {int(p) for p in items if isinstance(p, int)}


def listening(proc: Path, protocol: str) -> set[int]:
    ports: set[int] = set()
    for suffix in ("", "6"):
        lines = (proc / ("net/" + protocol + suffix)).read_text().splitlines()
        for line in lines[1:]:
            fields = line.split()
            if len(fields) < 4:
                raise ValueError("Malformed socket table")
            # TCP LISTEN or established sessions; any UDP socket prevents a false OFF.
            if protocol == "udp" or fields[3] in ("0A", "01"):
                ports.add(int(fields[1].rsplit(":", 1)[1], 16))
    return ports


def classify(
    profile: dict[str, object],
    status: dict[str, object],
    *,
    agent: bool,
    native: list[bool],
    marker: bool,
) -> int:
    """Latch alone is insufficient: actual unit ownership must agree."""
    if profile["component"] == "relay":
        if status.get("agent_active") is not agent or status.get("native_active") is not all(
            native
        ):
            return -1
        if status.get("fallback_marker") is not marker:
            return -1
        native_mode = status.get("mode") in ("native", "native-primary")
    else:
        native_mode = status.get("mode") == "fallback"
    if native_mode and marker and not agent and all(native):
        return 1
    if status.get("mode") == "kubernetes" and not marker and agent and not any(native):
        return 0
    return -1


def units_snapshot(units: list[str]) -> dict[str, bool]:
    result = command(
        ["systemctl", "show", *units, "-p", "Id", "-p", "LoadState", "-p", "ActiveState"], 5
    )
    if result.returncode:
        raise ValueError("Unobservable unit set")
    states: dict[str, bool] = {}
    for block in result.stdout.strip().split("\n\n"):
        fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if fields.get("LoadState") != "loaded":
            raise ValueError("Unloaded unit")
        states[fields["Id"]] = fields["ActiveState"] == "active"
    if set(states) != set(units):
        raise ValueError("Incomplete unit set")
    return states


def observe(
    profile: dict[str, object], proc: Path = Path("/proc"), *, live_check: bool = False
) -> dict[str, object]:
    before = Path(str(profile["marker"])).exists()
    cached = profile["component"] == "relay" and not live_check
    if cached:
        # Reuse the watchdog's actual persisted check. Do not add another TLS
        # handshake/CLI lock to the constrained Moscow relay every30seconds.
        path = Path(str(profile["marker"])).parent / "state.json"
        stamp = path.stat()
        status = json.loads(path.read_text())
        after = path.stat()
        if (stamp.st_ino, stamp.st_mtime_ns) != (after.st_ino, after.st_mtime_ns):
            raise ValueError("Concurrent state write")
        if type(status.get("healthy")) is not bool:
            raise ValueError("Missing cached health")
        status["data_path_healthy"] = status["healthy"]
        observed = stamp.st_mtime
    else:
        profile_command = profile["command"]
        if not isinstance(profile_command, list):
            reason = "Missing status command"
            raise ValueError(reason)
        result = command([str(x) for x in profile_command])
        if result.returncode not in (0, 1):
            raise ValueError("Status command failed")
        status = json.loads(result.stdout)
        observed = time.time()
    key = "data_path_healthy" if profile["component"] == "relay" else "healthy"
    if type(status.get(key)) is not bool:
        raise ValueError("Missing health observation")
    native_names = _unit_list(profile["native"])
    agent_unit = str(profile["agent"])
    states = units_snapshot([agent_unit, *native_names])
    agent = states[agent_unit]
    native = [states[u] for u in native_names]
    marker = Path(str(profile["marker"])).exists()
    if marker != before:
        raise ValueError("Concurrent runtime transition")
    if cached:
        status.update(agent_active=agent, native_active=all(native), fallback_marker=marker)
    runtime = classify(profile, status, agent=agent, native=native, marker=marker)
    tcp = listening(proc, "tcp")
    udp = listening(proc, "udp")
    off = not (tcp & _port_set(profile["tcp"]) or udp & _port_set(profile["udp"]))
    return {
        "runtime": runtime,
        "check_success": int(status[key]),
        "off": int(off),
        "observation_success": 1,
        "observed_timestamp_seconds": observed,
    }


def write_metrics(path: Path, component: str, values: dict[str, object]) -> None:
    lines = []
    for key, value in values.items():
        name = "socrat_vpn_component_" + key
        lines.extend(
            ["# TYPE " + name + " gauge", name + '{component="' + component + '"} ' + str(value)]
        )
    fd, name = tempfile.mkstemp(prefix=".vpn-runtime-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def audit(
    host: str, profile: dict[str, object], expected_image: str | None = None
) -> dict[str, object]:
    observation = observe(profile, live_check=True)
    native_units = [
        command(["systemctl", "cat", unit], 5).stdout for unit in _unit_list(profile["native"])
    ]
    agent = command(["systemctl", "cat", str(profile["agent"])], 5).stdout
    if host == "socrat-4":
        boot_fence = "ExecCondition=/usr/bin/test ! -e " + str(profile["marker"]) in agent
        native_fences = all(
            "ExecCondition=+/usr/bin/test -e " + str(profile["marker"]) in t for t in native_units
        )
        validation = (
            command(
                [
                    "/usr/local/libexec/xray-transit",
                    "run",
                    "-test",
                    "-config",
                    "/etc/homelab-vpn-transit/user.json",
                ]
            ).returncode
            == 0
        )
        route = command(["ip", "-4", "route", "get", "10.250.0.2"], 5).stdout
        extra = {
            "relay_config_valid": validation,
            "mesh_route_expected": "dev wg-socrat" in route and "src 10.250.0.40" in route,
            "relay_binary_sha256": hashlib.sha256(
                Path("/usr/local/libexec/xray-transit").read_bytes()
            ).hexdigest(),
        }
    else:
        config = json.loads(Path("/etc/homelab-vpn-failover/config.json").read_text())
        klass = runpy.run_path("/usr/local/sbin/homelab-vpn-failover")["Watchdog"]
        klass(config).preflight()  # read-only files + SQLite quick_check, no activation
        boot_fence = "ConditionPathExists=!" + str(profile["marker"]) in agent
        obsolete = command(["systemctl", "cat", "k3s-agent.service"], 5).stdout
        native_fences = all(
            "ConditionPathExists=" + str(profile["marker"]) in t
            and "homelab-vpn-failover guard" in t
            for t in native_units
        )
        validation = (
            command(
                [
                    "/opt/homelab-vpn-failover/caddy",
                    "validate",
                    "--config",
                    "/etc/homelab-vpn-failover/Caddyfile",
                    "--adapter",
                    "caddyfile",
                ]
            ).returncode
            == 0
        )
        actual = Path("/opt/homelab-vpn-failover/primary/.homelab-image").read_text().strip()
        extra = {
            "native_files_and_live_db_valid": True,
            "native_caddy_config_valid": validation,
            "native_image_matches_expected": bool(expected_image) and actual == expected_image,
            "configured_agent_is_server": config.get("agent_unit") == "k3s.service",
            "both_k3s_units_fenced": set(config.get("fenced_units", []))
            == {"k3s.service", "k3s-agent.service"},
            "obsolete_agent_boot_fenced": "ConditionPathExists=!" + str(profile["marker"])
            in obsolete,
            "watchdog_inhibited": Path("/var/lib/homelab-vpn-failover/inhibit").exists(),
        }
    nameservers = []
    for line in Path("/etc/resolv.conf").read_text().splitlines():
        if line.split()[:1] == ["nameserver"]:
            nameservers.append(line.split()[1])
    return {
        "host": host,
        "observation": observation,
        "watchdog_active": active(str(profile["timer"])),
        "watchdog_enabled": command(
            ["systemctl", "is-enabled", str(profile["timer"])], 5
        ).returncode
        == 0,
        "agent_boot_fenced": boot_fence,
        "native_boot_fenced": native_fences,
        "host_resolver_uses_cluster_dns": "10.43.0.10" in nameservers,
        **extra,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--expected-image")
    args = parser.parse_args()
    host = socket.gethostname()
    if os.geteuid() != 0 or host not in PROFILES:
        raise SystemExit("Requires intended local root host")
    profile = PROFILES[host]
    try:
        if args.audit:
            print(json.dumps(audit(host, profile, args.expected_image), sort_keys=True))
        else:
            write_metrics(OUTPUT, str(profile["component"]), observe(profile))
    except Exception:
        if not args.audit:
            write_metrics(
                OUTPUT,
                str(profile["component"]),
                {
                    "runtime": -1,
                    "check_success": 0,
                    "off": 0,
                    "observation_success": 0,
                    "observed_timestamp_seconds": 0,
                },
            )
        raise SystemExit(
            "VPN observer failed; telemetry unknown, no runtime actions taken."
        ) from None
