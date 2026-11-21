"""One direct DNS/TCP/TLS sample per resolved address. Sends no HTTP or bot data."""

import json
import sys
from collections import deque
from pathlib import Path
import socket
import ssl
from datetime import UTC, datetime
from time import monotonic, sleep


def elapsed(start):
    return round((monotonic() - start) * 1000, 1)


def samples(host, context):
    """Keep each candidate distinct; IPv6 failure does not imply IPv4 failure."""
    row = {"utc": datetime.now(UTC).isoformat(), "host": host}
    start = monotonic()
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        yield {
            **row,
            "dns_ms": elapsed(start),
            "stage": "dns",
            "error": type(exc).__name__,
        }
        return
    row["dns_ms"] = elapsed(start)
    for family, kind, proto, _, address in dict.fromkeys(addresses):
        result = {**row, "family": family.name, "ip": address[0]}
        stage = "tcp"
        start = monotonic()
        try:
            with socket.socket(family, kind, proto) as sock:
                sock.settimeout(3)
                sock.connect(address)
                result["tcp_ms"] = elapsed(start)
                stage = "tls"
                start = monotonic()
                with context.wrap_socket(sock, server_hostname=host):
                    result["tls_ms"] = elapsed(start)
            yield {**result, "stage": "ok"}
        except OSError as exc:
            yield {
                **result,
                f"{stage}_ms": elapsed(start),
                "stage": stage,
                "error": type(exc).__name__,
            }


def batch(context):
    return [
        row
        for target in ("api.telegram.org", "example.com")
        for row in samples(target, context)
    ]


def periodic(context):
    # Per-address diagnostics stay local. No unbounded container logs or IP labels.
    batches = deque(maxlen=120)
    target = Path("/samples/recent.json")
    while True:
        start = monotonic()
        batches.append(batch(context))
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(list(batches)))
        temp.replace(target)
        sleep(max(0, 30 - (monotonic() - start)))


if __name__ == "__main__":
    tls = ssl.create_default_context()
    if sys.argv[1:] == ["--periodic"]:
        periodic(tls)
    else:
        for sample in batch(tls):
            print(json.dumps(sample), flush=True)
