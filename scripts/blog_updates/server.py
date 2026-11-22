"""Internal serialized executor; externally verified GitHub events arrive via n8n."""

import hmac
import json
import os
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import override

from engine import UnsafeInput
from stages import stage

EXECUTION_LOCK = Lock()


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
        if not 0 < length <= 2_000_000:
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
                    write=os.environ.get("WRITE_ENABLED") == "true",
                )
            self.send_response(200)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
            result = {"status": "error", "type": type(exc).__name__}
            if isinstance(exc, UnsafeInput):
                result["reason"] = str(exc)
            self.send_response(422)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
