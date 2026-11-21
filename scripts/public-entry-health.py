#!/usr/bin/env python3
"""One bounded credential-free probe per owned HTTPS entrance; never change DNS.

Forced entry IP preserves Host/SNI/certificate verification. This is NOT ordinary
DNS/failover proof. Self/public hairpin checks are explicitly local-only evidence.
"""

import argparse
import http.client
import json
import socket
import ssl
import time
import urllib.parse

HOST = "auth.socrat.alchemmist.xyz"
PATH = "/application/o/rancher/.well-known/openid-configuration"
ISSUER = "https://" + HOST + "/application/o/rancher/"
ENTRIES = {"home": "109.173.40.247", "vps": "109.120.141.60", "internal": "192.168.0.250"}


def valid_discovery(data):
    """Execute valid_discovery."""
    if not isinstance(data, dict) or data.get("issuer") != ISSUER:
        return False
    for key in ["authorization_endpoint", "token_endpoint", "jwks_uri"]:
        value = data.get(key)
        if not isinstance(value, str):
            return False
        try:
            url = urllib.parse.urlsplit(value)
            if (
                url.scheme != "https"
                or url.hostname != HOST
                or url.username
                or url.password
                or url.port not in (None, 443)
            ):
                return False
        except ValueError:
            return False
    return True


def classify_failure(error):
    """Map an expected transport, TLS or JSON failure to its failure kind."""
    if isinstance(error, ssl.SSLCertVerificationError):
        return "tls_certificate"
    if isinstance(error, ssl.SSLError):
        return "tls_error"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(error, (ValueError, TypeError)):
        return "invalid_json_or_schema"
    if isinstance(error, (OSError, http.client.HTTPException)):
        return "transport_or_http_error"
    return None


def attempt_probe(entry, result, timeout, phase):
    """Drive one forced-IP probe attempt, updating result through phase states."""
    raw = None
    tls = None
    response = None
    try:
        raw = socket.create_connection((ENTRIES[entry], 443), timeout=timeout)
        result["tcp_ok"] = True
        phase["at"] = "tls"
        tls = ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
        result["tls_ok"] = True
        phase["at"] = "http"
        tls.sendall(
            (
                "GET "
                + PATH
                + " HTTP/1.1\r\nHost: "
                + HOST
                + "\r\nConnection: close\r\nAccept: application/json\r\n\r\n"
            ).encode()
        )
        response = http.client.HTTPResponse(tls)
        response.begin()
        result["http_status"] = response.status
        result["http_ok"] = response.status == 200
        phase["at"] = "body"
        body = response.read(65537)
        result["body_bytes"] = len(body)
        if len(body) > 65536:
            result["failure_kind"] = "body_bound"
        elif not result["http_ok"]:
            result["failure_kind"] = "http_status"
        else:
            phase["at"] = "backend_schema"
            result["backend_ok"] = valid_discovery(json.loads(body))
            if not result["backend_ok"]:
                result["failure_kind"] = "unexpected_discovery"
    finally:
        if response:
            response.close()
        if tls:
            tls.close()
        elif raw:
            raw.close()


def require_known_pair(entry, vantage) -> None:
    """Fail on unowned entries or vantages, keeping the LAN probe home-only."""
    if entry not in ENTRIES or vantage not in ["home", "vps", "workstation", "external"]:
        raise ValueError("Unknown owned entry or vantage")
    if entry == "internal" and vantage != "home":
        raise ValueError("Private LAN probe is home-only")


def probe(entry, vantage, timeout=3):
    """Execute probe."""
    require_known_pair(entry, vantage)
    started = time.monotonic()
    result = {
        "entry": entry,
        "vantage": vantage,
        "checked_at": int(time.time()),
        "tcp_ok": False,
        "tls_ok": False,
        "http_ok": False,
        "backend_ok": False,
        "local_only": entry == "internal" or entry == vantage or vantage == "workstation",
        "evidence": "forced-ip-host-sni; not normal DNS or client-failover acceptance",
    }
    phase = {"at": "tcp"}
    try:
        attempt_probe(entry, result, timeout, phase)
    except Exception as error:
        failure_kind = classify_failure(error)
        if failure_kind is None:
            raise
        result["failure_kind"] = failure_kind
    if not result["backend_ok"]:
        result["failure_phase"] = phase["at"]
    result["duration_ms"] = round((time.monotonic() - started) * 1000)
    return result


def main():
    """Execute main."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vantage", required=True, choices=["home", "vps", "workstation", "external"])
    p.add_argument("--entry", action="append", choices=ENTRIES)
    args = p.parse_args()
    entries = args.entry or (
        ["home", "vps", "internal"] if args.vantage == "home" else ["home", "vps"]
    )
    results = [probe(entry, args.vantage) for entry in dict.fromkeys(entries)]
    print(
        json.dumps({"writes": False, "credentials_used": False, "results": results}, sort_keys=True)
    )


if __name__ == "__main__":
    main()
