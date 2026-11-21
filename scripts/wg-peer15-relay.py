#!/usr/bin/env python3
"""Keyless, fixed-endpoint WG ciphertext relay; no general UDP forwarding.
Only node5 inside authenticated WG can send; only node1 fixed UDP can reply.
Never inspect/log/store payload, and never possess either peer's WG private key.
"""

import json
import select
import signal
import socket
import time

FRONT = ("10.250.0.1", 51835)
CLIENT = ("10.250.0.41", 51830)
BACK = ("192.168.0.23", 51836)
TARGET = ("192.168.0.24", 51830)


def main():
    alive = True

    def stop(_signum, _frame):
        nonlocal alive
        alive = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    back = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for s in (front, back):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
    front.bind(FRONT)
    back.bind(BACK)
    back.connect(TARGET)
    stats = {"accepted": 0, "returned": 0, "rejected": 0, "errors": 0}
    print(
        json.dumps(
            {"state": "ready", "front": FRONT, "client": CLIENT, "back": BACK, "target": TARGET}
        ),
        flush=True,
    )
    report = time.monotonic()
    try:
        while alive:
            for s in select.select([front, back], [], [], 0.5)[0]:
                try:
                    data, source = s.recvfrom(65535)
                    if s is front:
                        if source != CLIENT or len(data) < 4:
                            stats["rejected"] += 1
                            continue
                        back.send(data)
                        stats["accepted"] += 1
                    else:
                        # Connected UDP socket enforces exact fixed source.
                        front.sendto(data, CLIENT)
                        stats["returned"] += 1
                except OSError:
                    # E.g. target ICMP errors do not create an uncontrolled
                    # restart loop, arbitrary target or fallback WAN route.
                    stats["errors"] += 1
            if time.monotonic() - report >= 15:
                print(json.dumps(stats), flush=True)
                report = time.monotonic()
    finally:
        front.close()
        back.close()
        print(json.dumps({"state": "stopped", **stats}), flush=True)


if __name__ == "__main__":
    main()
