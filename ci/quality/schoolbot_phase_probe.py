"""One fixed, read-only HTTP timing sample inside a disposable Socrat listener Pod.

Caller supplies the freshly verified Schoolbot Service VIP and bounds total runtime
(including resolver calls). No credentials, redirects, arbitrary URL or body output.
This separate socket cannot explain another process's connection by itself.
"""

import argparse
import http.client
import ipaddress
import json
import socket
import time

SERVICE = "schoolbot.schoolbot.svc.cluster.local"
REQUEST = b"GET /api/health HTTP/1.0\r\nHost: inform.sch1357.ru\r\nConnection: close\r\n\r\n"


def sample(mode, vip):
    address = ipaddress.IPv4Address(vip)
    if address not in ipaddress.IPv4Network("10.43.0.0/16") or mode not in {
        "named",
        "absolute",
        "numeric",
        "listener",
    }:
        raise ValueError("unexpected probe destination")
    result = {}
    phase = "dns"
    start = time.monotonic_ns()

    def finish(label):
        nonlocal start
        now = time.monotonic_ns()
        result[label + "_ms"] = round((now - start) / 1e6, 2)
        start = now

    try:
        if mode in {"named", "absolute"}:
            answers = socket.getaddrinfo(
                SERVICE + ("." if mode == "absolute" else ""),
                80,
                socket.AF_INET,
                socket.SOCK_STREAM,
            )
            finish("dns")
            if {row[4] for row in answers} != {(str(address), 80)}:
                return {**result, "outcome": "unexpected-dns"}
        phase = "tcp"
        dest = ("127.0.0.1", 8181) if mode == "listener" else (str(address), 80)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(6)
            sock.connect(dest)
            finish("tcp")
            phase = "headers"
            sock.sendall(REQUEST)
            with http.client.HTTPResponse(sock) as response:
                response.begin()
                finish("headers")
                if response.status != 200:
                    return {**result, "outcome": f"http-{response.status}"}
                phase = "body"
                body = response.read(8193)
                finish("body")
                doc = json.loads(body) if len(body) <= 8192 else None
                valid = (
                    response.headers.get_all("Content-Length") == [str(len(body))]
                    and response.getheader("Transfer-Encoding") is None
                    and response.getheader("Content-Type", "").partition(";")[0]
                    == "application/json"
                    and len(body) <= 8192
                    and isinstance(doc, dict)
                    and doc.get("ok") is True
                )
                return {**result, "outcome": "healthy" if valid else "invalid-health"}
    except (OSError, ValueError, http.client.HTTPException):
        finish(phase)
        return {**result, "outcome": phase + "-failed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["absolute", "named", "numeric", "listener"])
    parser.add_argument("vip")
    args = parser.parse_args()
    print(json.dumps(sample(args.mode, args.vip)))
