"""One direct DNS/TCP/TLS sample per resolved address. Sends no HTTP or bot data."""

import json
import socket
import ssl
from datetime import UTC, datetime
from time import monotonic


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


if __name__ == "__main__":
    tls = ssl.create_default_context()
    for target in ("api.telegram.org", "example.com"):
        for sample in samples(target, tls):
            print(json.dumps(sample), flush=True)
