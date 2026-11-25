"""Internal worker. n8n forwards a signed GitHub push; this process checks the spec."""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import TYPE_CHECKING, override

from .engine import UnsafeInputError
from .workflow import stage

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_BODY_BYTES = 2_000_000
# The pod spec passes LISTEN_BIND; binding the container's configured interface is
# intentional and NetworkPolicy plus the ingress edge gate reachability.
LISTEN_BIND = os.environ["LISTEN_BIND"]
LISTEN_PORT = 8080

LOCK = Lock()
PATHS = {"/check", "/render", "/create-pr", "/close-older"}


class Handler(BaseHTTPRequestHandler):
    """HTTP handler serving the wiki OpenAPI frontend."""

    @override
    def log_message(self, *args: object) -> None:
        """Silence default request-line logging."""

    def do_GET(self) -> None:
        """Answer liveness probes on /healthz and 404 otherwise."""
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def do_POST(self) -> None:
        """Dispatch an authenticated worker action on the allowed paths."""
        if self.path not in PATHS or not hmac.compare_digest(
            self.headers.get("X-Worker-Token", ""), os.environ["WORKER_TOKEN"]
        ):
            self.send_response(403)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_BODY_BYTES:
            self.send_response(413)
            self.end_headers()
            return
        result: list[Mapping[str, object]] | dict[str, str]
        try:
            payload = json.loads(self.rfile.read(length))
            with LOCK:
                result = stage(
                    self.path[1:],
                    payload,
                    write=os.environ.get("WRITE_ENABLED") == "true",
                )
            code = 200
        except (OSError, ValueError, KeyError, TypeError, UnsafeInputError) as exc:
            result = {"status": "error", "type": type(exc).__name__}
            if isinstance(exc, UnsafeInputError):
                result["reason"] = str(exc)
            code = 422
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())


if __name__ == "__main__":
    ThreadingHTTPServer((LISTEN_BIND, LISTEN_PORT), Handler).serve_forever()
