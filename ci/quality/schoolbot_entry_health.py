"""Explicit anonymous Schoolbot TLS/health probe; never a DNS or isolation test."""

import argparse
import http.client
import ipaddress
import json
import socket
import ssl

import yaml

from ci.quality.public_web import CATALOG

HOST = "inform.sch1357.ru"
LIMIT = 8192


def _unique(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate JSON key")
    return result


def healthy(status: int, content_type: str, body: bytes) -> bool:
    if (
        status != 200
        or content_type.partition(";")[0].strip().lower() != "application/json"
        or len(body) > LIMIT
    ):
        return False
    try:
        doc = json.loads(body.decode("utf-8"), object_pairs_hook=_unique)
    except (ValueError, RecursionError):
        return False
    return isinstance(doc, dict) and doc.get("ok") is True


def response_healthy(resp: http.client.HTTPResponse) -> bool:
    """Do not accept a valid-looking JSON prefix of a truncated response."""
    length = resp.getheader("Content-Length")
    if length is not None:
        if (
            not length.isascii()
            or not length.isdecimal()
            or len(length) > 10
            or int(length) > LIMIT
            or resp.getheader("Transfer-Encoding") is not None
        ):
            return False
    body = resp.read(LIMIT + 1)
    if length is None and len(body) <= LIMIT and resp.read(1):
        return False  # Do not accept a short read when more body bytes follow.
    if length is not None and len(body) != int(length):
        return False
    return healthy(resp.status, resp.getheader("Content-Type", ""), body)


def probe(ip: str, port: int) -> str:
    phase = "tcp"
    try:
        with socket.create_connection((ip, port), timeout=5) as raw:
            phase = "tls"
            with ssl.create_default_context().wrap_socket(raw, server_hostname=HOST) as conn:
                phase = "http"
                conn.settimeout(6)
                conn.sendall(
                    f"GET /api/health HTTP/1.1\r\nHost: {HOST}\r\nAccept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n".encode(
                        "ascii"
                    )
                )
                with http.client.HTTPResponse(conn) as resp:
                    resp.begin()
                    if resp.status != 200:
                        return f"http-{resp.status}"
                    if not response_healthy(resp):
                        return "unexpected-health-response"
                    return "trusted-tls-and-health-ok"
    except ssl.SSLCertVerificationError as exc:
        return f"tls-verification-failed-{exc.verify_code}"
    except (OSError, http.client.HTTPException):
        return f"{phase}-failed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument(
        "--public",
        action="store_true",
        help="Probe every inventory IPv4 directly with the Schoolbot SNI.",
    )
    choice.add_argument(
        "--local-port",
        type=int,
        help="Probe an already-established loopback-only port-forward to a closed HTTPS listener.",
    )
    args = parser.parse_args()
    catalog = yaml.safe_load(CATALOG.read_text())
    policy = catalog
    for key in ("hosts", "schoolbot", HOST):
        policy = policy.get(key) if isinstance(policy, dict) else None
    if not isinstance(policy, dict):
        parser.error("missing Schoolbot host policy")
    if policy.get("dns") != "external" or policy.get("route", "web") != "web":
        parser.error("Schoolbot name is not an eligible external web route")
    if args.public:
        targets = [
            (name, str(ipaddress.IPv4Address(item["publicIP"])), 443)
            for name, item in catalog["replicas"].items()
        ]
    else:
        if not 1 <= args.local_port <= 65535:
            parser.error("invalid loopback port")
        targets = [("private-loopback", "127.0.0.1", args.local_port)]
    ok = bool(targets)
    for label, ip, port in targets:
        result = probe(ip, port)
        print(f"{label}: {result}")
        ok = ok and result == "trusted-tls-and-health-ok"
    return int(not ok)


if __name__ == "__main__":
    raise SystemExit(main())
