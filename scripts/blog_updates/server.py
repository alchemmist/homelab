"""Internal serialized executor; externally verified GitHub events arrive via n8n."""

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import TYPE_CHECKING, override

from .core import UnsafeInputError
from .workflow import stage

if TYPE_CHECKING:
    from collections.abc import Mapping

EXECUTION_LOCK = Lock()
# One push event with base64 file payloads stays small; bound requests at 2 MB.
MAX_REQUEST_BYTES = 2_000_000
# The pod spec passes LISTEN_BIND; binding the container's configured interface is
# intentional and NetworkPolicy plus the ingress edge gate reachability.
LISTEN_BIND = os.environ["LISTEN_BIND"]
LISTEN_PORT = 8080


class Handler(BaseHTTPRequestHandler):
    """HTTP handler serving blog update status."""

    @override
    def log_message(self, *args: object) -> None:
        """Silence request logging: no bodies, credentials or content in logs."""
        # no request bodies, credentials or content in logs

    def do_GET(self) -> None:
        """Answer liveness probes on /healthz and 404 otherwise."""
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def do_POST(self) -> None:
        """Dispatch an authenticated worker action (validate/generate/create-pr)."""
        if self.path not in (
            "/validate",
            "/generate",
            "/create-pr",
        ) or not hmac.compare_digest(
            self.headers.get("X-Worker-Token", ""), os.environ["WORKER_TOKEN"]
        ):
            self.send_response(403)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_REQUEST_BYTES:
            self.send_response(413)
            self.end_headers()
            return
        result: list[Mapping[str, object]] | dict[str, str]
        try:
            event = json.loads(self.rfile.read(length))
            with EXECUTION_LOCK:
                result = stage(
                    self.path[1:],
                    event,
                    publish=os.environ.get("WRITE_ENABLED") == "true",
                )
            self.send_response(200)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
            result = {"status": "error", "type": type(exc).__name__}
            if isinstance(exc, UnsafeInputError):
                result["reason"] = str(exc)
            self.send_response(422)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())


def serve() -> None:
    """Bind every pod interface and serve until the process is stopped."""
    ThreadingHTTPServer((LISTEN_BIND, LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    serve()
