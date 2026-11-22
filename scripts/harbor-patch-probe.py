#!/usr/bin/env python3
"""Time one disposable 1 MiB registry PATCH; do not finalize a blob or tag."""

import argparse
import base64
import http.client
import ipaddress
import json
import os
import secrets
import socket
import ssl
import time
from urllib.parse import urlencode, urljoin, urlsplit

HOST = "harbor.socrat.alchemmist.xyz"
REPO = "homelab/transfer-diagnostics"
PREFIX = f"/v2/{REPO}/blobs/uploads/"


def upload_path(location):
    """Reject off-origin upload locations before sending any upload credentials."""
    u = urlsplit(urljoin(f"https://{HOST}{PREFIX}", location or ""))
    if (u.scheme, u.netloc) != ("https", HOST) or not u.path.startswith(PREFIX):
        raise ValueError("Unexpected registry upload origin")
    suffix = u.path[len(PREFIX) :]
    if not suffix or any(c not in "0123456789abcdef-" for c in suffix.lower()):
        raise ValueError("Unexpected registry upload ID")
    return u.path + ("?" + u.query if u.query else "")


def main():
    """Authenticate with a test writer, measure PATCH only, and cancel the session."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--address", type=ipaddress.ip_address, required=True)
    args = p.parse_args()
    ctx = ssl.create_default_context()

    def request(method, path, auth, body=None):
        conn = http.client.HTTPSConnection(HOST, context=ctx, timeout=100)
        with socket.create_connection((str(args.address), 443), timeout=100) as raw:
            conn.sock = ctx.wrap_socket(raw, server_hostname=HOST)
            try:
                start = time.monotonic()
                conn.request(
                    method,
                    path,
                    body,
                    {"Authorization": auth, "Content-Type": "application/octet-stream"},
                )
                r = conn.getresponse()
                data = r.read(65537)
                if len(data) > 65536:
                    raise ValueError("Response exceeded metadata limit")
                return r.status, r.headers, data, time.monotonic() - start
            finally:
                conn.close()

    basic = base64.b64encode(
        (os.environ["HARBOR_TEST_USER"] + ":" + os.environ["HARBOR_TEST_PASSWORD"]).encode()
    ).decode()
    q = urlencode({"service": "harbor-registry", "scope": f"repository:{REPO}:pull,push"})
    status, _, payload, _ = request("GET", "/service/token?" + q, "Basic " + basic)
    if status != 200:
        raise SystemExit(f"Token request: HTTP {status}")
    auth = "Bearer " + json.loads(payload)["token"]
    layer = secrets.token_bytes(1024 * 1024)
    status, headers, _, _ = request("POST", PREFIX, auth, b"")
    if status != 202:
        raise SystemExit(f"Upload initialization: HTTP {status}; no retry")
    path = upload_path(headers.get("Location"))
    try:
        status, headers, _, elapsed = request("PATCH", path, auth, layer)
        if status != 202:
            raise SystemExit(f"Upload PATCH: HTTP {status}; no retry")
        next_path = upload_path(headers.get("Location"))
        if urlsplit(next_path).path != urlsplit(path).path:
            raise ValueError("Registry changed the upload session ID")
        path = next_path
        if headers.get("Range") != f"0-{len(layer) - 1}":
            raise ValueError("Registry did not acknowledge the entire payload")
        print(
            json.dumps(
                {
                    "address": str(args.address),
                    "bytes": len(layer),
                    "patch_seconds": elapsed,
                    "KiB_per_second": len(layer) / 1024 / elapsed,
                }
            )
        )
    finally:
        status, _, _, _ = request("DELETE", path, auth)
        if status != 204:
            raise SystemExit(f"Upload cancellation: HTTP {status}; reconcile before rerunning")


if __name__ == "__main__":
    main()
