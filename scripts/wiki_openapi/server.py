"""Internal worker. n8n forwards a signed GitHub push; this process checks the spec."""
import hmac
import json
import os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Lock
from engine import UnsafeInput
from stages import stage

LOCK = Lock()
PATHS = {'/check', '/render', '/create-pr', '/close-older'}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200 if self.path == '/healthz' else 404)
        self.end_headers()

    def do_POST(self):
        if self.path not in PATHS or not hmac.compare_digest(self.headers.get('X-Worker-Token', ''), os.environ['WORKER_TOKEN']):
            self.send_response(403); self.end_headers(); return
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 2_000_000:
            self.send_response(413); self.end_headers(); return
        try:
            payload = json.loads(self.rfile.read(length))
            with LOCK:
                result = stage(self.path[1:], payload, write=os.environ.get('WRITE_ENABLED') == 'true')
            code = 200
        except Exception as exc:
            result = {'status': 'error', 'type': type(exc).__name__}
            if isinstance(exc, UnsafeInput):
                result['reason'] = str(exc)
            code = 422
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
