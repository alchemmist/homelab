#!/usr/bin/env python3
"""Put configured wg-socrat endpoints back when WireGuard roaming moves them.

Peers with an Endpoint in /etc/wireguard/wg-socrat.conf are fixed infrastructure.
Roaming may retarget them at an address inside the tunnel (the peer's own
10.250.0.0/24 address). That drops the underlay. Peers without Endpoint stay
free to roam. The config file is not rewritten.
"""

import json
import re
import socket
import subprocess
import sys
from pathlib import Path

CONFIG = Path("/etc/wireguard/wg-socrat.conf")
INTERFACE = "wg-socrat"


def configured_endpoints(text: str) -> dict[str, str]:
    parts = re.split(r"(?m)(?=^\[Peer\]\s*$)", text)
    found: dict[str, str] = {}
    for part in parts:
        if not part.startswith("[Peer]"):
            continue
        keys = re.findall(r"(?m)^PublicKey\s*=\s*(\S+)\s*$", part)
        endpoints = re.findall(r"(?m)^Endpoint\s*=\s*(\S+)\s*$", part)
        if len(keys) != 1 or len(endpoints) != 1:
            continue
        if keys[0] in found:
            msg = "Duplicate pinned peer"
            raise ValueError(msg)
        found[keys[0]] = endpoints[0]
    return found


def runtime_endpoints(text: str) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        key, _, value = line.partition("\t")
        if not value:
            key, _, value = line.partition(" ")
        if key and value and value != "(none)":
            found[key] = value
    return found


def drifts(
    configured: dict[str, str], runtime: dict[str, str]
) -> list[tuple[str, str, str | None]]:
    return [
        (key, want, runtime.get(key))
        for key, want in configured.items()
        if runtime.get(key) != want
    ]


def home_underlay(wanted):
    """Prefer direct WG transport only on worker 3's verified home Wi-Fi LAN."""
    if (
        socket.gethostname().split(".")[0] != "socrat-3"
        or "109.173.40.247:51830" not in wanted.values()
    ):
        return

    def ip(*args):
        return json.loads(subprocess.check_output(["ip", "-j", *args], text=True))

    dev = "wlp1s0"
    gateway = "192.168.0.1"
    home = any(
        r.get("dev") == dev and r.get("gateway") == gateway
        for r in ip("route", "show", "default")
    ) and any(
        r.get("lladdr", "").lower() == "48:29:e4:83:22:f0" and r.get("dev") == dev
        for r in ip("neigh", "show", "to", gateway)
    )
    if not home:
        return  # retain configured WAN endpoint; source route applies only to LAN UDP
    subnet = "192.168.0.23/32"
    subprocess.run(
        ["ip", "route", "replace", "table", "183", subnet, "dev", dev], check=True
    )
    rules = ip("rule", "show")
    if not any(r.get("priority") == 30183 for r in rules):
        subprocess.run(
            [
                "ip",
                "rule",
                "add",
                "pref",
                "30183",
                "to",
                subnet,
                "ipproto",
                "udp",
                "dport",
                "51830",
                "lookup",
                "183",
            ],
            check=True,
        )
    for peer, endpoint in wanted.items():
        if endpoint == "109.173.40.247:51830":
            wanted[peer] = "192.168.0.23:51830"


def main() -> None:
    text = CONFIG.read_text()
    if re.search(r"(?mi)^SaveConfig\s*=\s*true\s*$", text):
        print(json.dumps({"reset": 0, "skipped": "SaveConfig"}))
        return
    wanted = configured_endpoints(text)
    home_underlay(wanted)
    current = runtime_endpoints(
        subprocess.check_output(["wg", "show", INTERFACE, "endpoints"], text=True)
    )
    moved = drifts(wanted, current)
    for key, want, _have in moved:
        subprocess.check_call(["wg", "set", INTERFACE, "peer", key, "endpoint", want])
    print(json.dumps({"reset": len(moved)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"wg-socrat-pin-endpoints: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
