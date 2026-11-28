#!/usr/bin/env python3
"""Forced-command SSH witness: test a dedicated synthetic Trojan/WS/TLS identity."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def probe():
    # Provisioned ONLY on the independent witness. Never use a customer's account.
    cfg = json.loads(Path("/etc/homelab-vpn-witness/client.json").read_text())
    (upstream,) = cfg["outbounds"]
    (server,) = upstream["settings"]["servers"]
    stream = upstream["streamSettings"]
    if not (
        upstream["protocol"] == "trojan"
        and server["address"] == "vpn.alchemmist.xyz"
        and server["port"] == 443
        and stream["security"] == "tls"
        and stream["network"] == "ws"
        and not stream.get("tlsSettings", {}).get("allowInsecure")
    ):
        msg = "Unexpected witness configuration"
        raise ValueError(msg)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "probe.json"
        path.write_text(
            json.dumps(
                {
                    "log": {"loglevel": "none"},
                    "inbounds": [
                        {
                            "listen": "127.0.0.1",
                            "port": port,
                            "protocol": "socks",
                            "settings": {"auth": "noauth"},
                        }
                    ],
                    "outbounds": [upstream],
                }
            )
        )
        with subprocess.Popen(
            ["/usr/local/bin/xray", "run", "-c", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as proc:
            try:
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        return False
                    try:
                        with socket.create_connection(("127.0.0.1", port), 0.1):
                            break
                    except OSError:
                        time.sleep(0.025)
                else:
                    return False
                r = subprocess.run(
                    [
                        "/usr/bin/curl",
                        "-q",
                        "--silent",
                        "--noproxy",
                        "",
                        "--proxy",
                        f"socks5h://127.0.0.1:{port}",
                        "--max-time",
                        "3",
                        "--output",
                        "/dev/null",
                        "--write-out",
                        "%{http_code}",
                        "https://example.com/",
                    ],
                    capture_output=True,
                    timeout=4,
                )
                return proc.poll() is None and r.returncode == 0 and r.stdout == b"200"
            finally:
                proc.kill()


if __name__ == "__main__":
    os.umask(0o077)
    try:
        ok = probe()
    except Exception:
        ok = False
    sys.exit(0 if ok else 1)
