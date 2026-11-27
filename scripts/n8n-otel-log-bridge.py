"""n8n log-streaming webhook to otel-loki push bridge; stdlib only, no payload logging.

Runs as a sidecar inside the n8n pod. Accepts n8n log-streaming webhook posts on
127.0.0.1:<port>/event, converts each event into one Loki push stream entry, and
forwards it to otel-loki over mTLS using the dedicated n8n client leaf. The SSL
context is rebuilt when the mounted certificate files change (cert-manager leaf
rotation), so no pod reload is required.
"""
import json
import os
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("BRIDGE_PORT", "9123"))
LOKI_URL = os.environ["LOKI_URL"].rstrip("/")
LOKI_SERVER_NAME = os.environ["LOKI_SERVER_NAME"]
TLS_DIR = os.environ.get("TLS_DIR", "/etc/otel-tls")

_lock = threading.Lock()
_ssl_context = None
_ssl_stamp = None


def ssl_context():
    """Return a verified client SSL context, rebuilding it after leaf rotation."""
    global _ssl_context, _ssl_stamp
    cert = os.path.join(TLS_DIR, "tls.crt")
    key = os.path.join(TLS_DIR, "tls.key")
    ca = os.path.join(TLS_DIR, "ca.crt")
    stamp = (file_stamp(cert), file_stamp(key), file_stamp(ca))
    with _lock:
        if _ssl_context is None or stamp != _ssl_stamp:
            context = ssl.create_default_context(cafile=ca)
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_cert_chain(cert, key)
            _ssl_context = context
            _ssl_stamp = stamp
        return _ssl_context


def file_stamp(path):
    """Return an mtime tuple robust to not-yet-mounted files."""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def push_to_loki(stream_labels, line, timestamp_ns):
    """Push one JSON log line to otel-loki; raise on non-2xx."""
    payload = json.dumps(
        {"streams": [{"stream": stream_labels, "values": [[str(timestamp_ns), line]]}]}
    ).encode()
    request = urllib.request.Request(
        LOKI_URL + "/loki/api/v1/push",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10, context=ssl_context()) as response:
        response.read()


def event_labels(event):
    """Map a n8n log-streaming event to Loki stream labels.

    n8n sends `eventName` and nests `workflowId` inside `payload`; keep the
    event-shaped fallbacks for forwards-compatibility.
    """
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return {
        "job": "n8n",
        "source": "n8n-log-streaming",
        "event": str(event.get("eventName", event.get("event", "unknown")))[:64],
        "workflow_id": str(
            event.get("workflowId", payload.get("workflowId", ""))
        )[:64]
        or "none",
    }


class Handler(BaseHTTPRequestHandler):
    """Convert n8n log-streaming events into Loki entries."""

    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - http.server API
        if self.path not in ("/event", "/event/"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            event = json.loads(body)
            labels = event_labels(event)
            timestamp_ns = str(time.time_ns())
            push_to_loki(labels, json.dumps(event, separators=(",", ":")), timestamp_ns)
            self.send_response(200)
        except Exception:
            # Never leak payload details; n8n only needs the status code.
            self.send_response(502)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        """Silence per-request access logs; events may contain workflow context."""


def main():
    """Serve until stopped."""
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
