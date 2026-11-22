"""One direct DNS/TCP/TLS sample per resolved address. Sends no HTTP or bot data."""

import json
import socket
import ssl
import subprocess
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep


def elapsed(start):
    return round((monotonic() - start) * 1000, 1)


def resolve(host):
    # libc getaddrinfo has no portable timeout. Reap the isolated resolver even
    # when a nameserver stops answering; a timed-out thread would keep running.
    program = "import json,socket,sys; print(json.dumps(socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)))"
    try:
        result = subprocess.run(
            [sys.executable, "-c", program, host], capture_output=True, timeout=3
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("DNS deadline") from exc
    if result.returncode:
        raise socket.gaierror("resolution failed")
    try:
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or not rows:
            raise ValueError("expected resolved addresses")
        return [
            (socket.AddressFamily(f), k, p, n, tuple(a))
            for f, k, p, n, a in rows
        ]
    except (ValueError, TypeError) as exc:
        raise socket.gaierror("invalid resolver response") from exc


def samples(host, context):
    """Keep each candidate distinct; IPv6 failure does not imply IPv4 failure."""
    row = {"utc": datetime.now(UTC).isoformat(), "host": host}
    start = monotonic()
    try:
        addresses = resolve(host)
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
    storage_failed = False
    while True:
        start = monotonic()
        batches.append(batch(context))
        temp = target.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(list(batches)))
            temp.replace(target)
        except OSError as exc:
            if not storage_failed:
                print("sample publication failed:", type(exc).__name__, file=sys.stderr, flush=True)
            storage_failed = True
        else:
            storage_failed = False
        # Skip missed ticks rather than immediately launching a catch-up batch.
        sleep(30 - ((monotonic() - start) % 30))


if __name__ == "__main__":
    tls = ssl.create_default_context()
    if sys.argv[1:] == ["--periodic"]:
        periodic(tls)
    else:
        for sample in batch(tls):
            print(json.dumps(sample), flush=True)
