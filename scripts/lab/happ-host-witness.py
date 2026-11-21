"""Read-only witness on socrat-1 while an operator cycles VPN inside a guest."""

import hashlib
import json
import socket
import subprocess
import sys
import time


def cmd(*args):
    return subprocess.check_output(args, text=True, timeout=3).strip()


def route(ip):
    row = json.loads(cmd("ip", "-j", "-4", "route", "get", ip))[0]
    return {
        key: row[key] for key in ("gateway", "dev", "prefsrc", "table") if key in row
    }


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def sample():
    rules = [cmd("ip", family, "rule", "show") for family in ("-4", "-6")]
    # Fingerprint full policy and main table locally; never publish their contents.
    tables = [
        cmd("ip", family, "route", "show", "table", "all") for family in ("-4", "-6")
    ]
    sessions = cmd("ss", "-Hnt", "state", "established", "dst", "91.189.82.238:51840")
    flows = [
        " ".join(line.split()[-2:]) for line in sessions.splitlines() if line.strip()
    ]
    if not flows:
        raise RuntimeError("no established GOST relay TCP connection")
    if any(
        i["ifname"] == "happ-xray" for i in json.loads(cmd("ip", "-j", "link", "show"))
    ):
        raise RuntimeError("host Happ interface is present")
    with socket.create_connection(("10.250.0.2", 2380), timeout=2):
        pass
    return {
        "relay_route": route("91.189.82.238"),
        "mesh_route": route("10.250.0.2"),
        "rule_hash": digest("\n".join(rules)),
        "table_hash": digest("\n".join(tables)),
        "flows": set(map(digest, flows)),
    }


def main():
    if socket.gethostname().split(".")[0] != "socrat-1" or len(sys.argv) != 2:
        raise SystemExit("usage on socrat-1: happ-host-witness.py SECONDS (5..600)")
    seconds = int(sys.argv[1])
    if not 5 <= seconds <= 600:
        raise SystemExit("bounded sample window required")
    original = sample()
    survivors = original.pop("flows")
    start = time.monotonic()
    print("baseline verified; start guest-only cycles now", flush=True)
    while time.monotonic() - start < seconds:
        time.sleep(2)
        current = sample()
        survivors &= current.pop("flows")
        if current != original or not survivors:
            raise SystemExit(
                "host witness changed; stop acceptance and investigate, do not alter host routes"
            )
    print(
        "witness passed: sampled host state and an original relay tuple persisted; guest VPN state must be verified independently"
    )


if __name__ == "__main__":
    main()
