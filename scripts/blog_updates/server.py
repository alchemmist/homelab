"""Internal serialized executor; externally verified GitHub events arrive via n8n."""
import hmac
import json
import os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Lock
EXECUTION_LOCK = Lock()
from stages import stage
from engine import UnsafeInput
from github import GitHub

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # no request bodies, credentials or content in logs

    def do_GET(self):
        self.send_response(200 if self.path == '/healthz' else 404)
        self.end_headers()

    def do_POST(self):
        if self.path not in ('/validate', '/generate', '/create-pr') or not hmac.compare_digest(
                self.headers.get('X-Worker-Token', ''), os.environ['WORKER_TOKEN']):
            self.send_response(403); self.end_headers(); return
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 2_000_000:
            self.send_response(413); self.end_headers(); return
        try:
            event = json.loads(self.rfile.read(length))
            with EXECUTION_LOCK:
                result = stage(self.path[1:], event, write=os.environ.get('WRITE_ENABLED') == 'true')
            self.send_response(200)
        except Exception as exc:
            result = {'status': 'error', 'type': type(exc).__name__}
            if isinstance(exc, UnsafeInput): result['reason'] = str(exc)
            self.send_response(422)
        self.send_header('Content-Type', 'application/json'); self.end_headers()
        self.wfile.write(json.dumps(result).encode())

ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
