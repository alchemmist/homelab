"""Private queue BFF. Ingress SSO + Traefik-only NetworkPolicy are mandatory.
Only two fixed operator routes; no worker token, cookies or caller headers forwarded.
"""
import http.client
import http.server
import json
from pathlib import Path
import socket
import threading

ORIGIN = 'https://rustfs.socrat.alchemmist.xyz'
ASSETS = {'/queue/': ('index.html', 'text/html; charset=utf-8'),
          '/queue/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/queue/style.css': ('style.css', 'text/css; charset=utf-8')}
ROUTES = {'/queue/api/list': '/operator/queue/list', '/queue/api/cancel': '/operator/queue/cancel'}
TOKEN = ''

def expire(sock):
    try:sock.shutdown(socket.SHUT_RDWR)
    except OSError:pass

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):pass
    def handle(self):
        timer = threading.Timer(20, expire, (self.request,))
        timer.daemon = True
        timer.start()
        try:
            self.request.settimeout(10)
            super().handle()
        finally:timer.cancel()

    def send_error(self, code, message=None, explain=None):
        self.send(400, b'', 'text/plain')

    def send(self, status, body, mime='application/json; charset=utf-8', location=None):
        self.close_connection = True
        self.send_response(status)
        for k, v in {'Content-Type': mime, 'Content-Length': str(len(body)),
                     'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                     'Referrer-Policy': 'no-referrer', 'Connection': 'close',
                     'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'"}.items():
            self.send_header(k, v)
        if location:self.send_header('Location', location)
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):pass

    def valid_host(self):
        # Ingress removes caller identity headers before authenticated response
        # headers are copied; NetworkPolicy admits only Traefik to this service.
        return self.headers.get_all('Host', []) == ['rustfs.socrat.alchemmist.xyz']

    def permitted(self):
        return bool(set(self.headers.get('X-authentik-groups', '').split('|'))
                    & {'homelab-owner', 'homelab-platform-operator'})

    def do_GET(self):
        if not self.valid_host():return self.send(400, b'{}')
        if not self.permitted():return self.send(403, b'{}')
        if self.path == '/queue':return self.send(308, b'', location='/queue/')
        asset = ASSETS.get(self.path)
        if not asset:return self.send(404, b'{}')
        self.send(200, Path(__file__).with_name(asset[0]).read_bytes(), asset[1])

    def do_POST(self):
        if not self.valid_host():return self.send(400, b'{}')
        if not self.permitted():return self.send(403, b'{}')
        if (self.headers.get_all('Origin', []) != [ORIGIN]
                or self.headers.get('X-SPI-Queue') != '1'
                or self.headers.get('Sec-Fetch-Site', 'same-origin') != 'same-origin'):
            return self.send(403, b'{"code":"CSRF_REJECTED"}')
        route = ROUTES.get(self.path)
        if not route:return self.send(404, b'{}')
        lengths = self.headers.get_all('Content-Length', [])
        if (self.headers.get('Transfer-Encoding') is not None or len(lengths) != 1
                or len(lengths[0]) > 4 or not lengths[0].isascii() or not lengths[0].isdecimal()
                or not 0 < int(lengths[0]) <= 2048
                or self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json'):
            return self.send(400, b'{"code":"INVALID_REQUEST"}')
        connection = None
        try:
            raw = self.rfile.read(int(lengths[0]))
            if len(raw) != int(lengths[0]) or not isinstance(json.loads(raw), dict):
                return self.send(400, b'{"code":"INVALID_REQUEST"}')
            connection = http.client.HTTPConnection('spi-triage.automation.svc.cluster.local', 8080, timeout=8)
            connection.request('POST', route, body=raw, headers={'Content-Type':'application/json', 'X-Queue-Token':TOKEN})
            response = connection.getresponse()
            body = response.read(512001)
            if len(body) > 512000 or response.status not in (200, 400, 403, 409):
                return self.send(502, b'{"code":"QUEUE_UNAVAILABLE"}')
            data = json.loads(body)
            if not isinstance(data, dict):raise ValueError()
            self.send(response.status, json.dumps(data).encode())
        except (ValueError, OSError, http.client.HTTPException):
            self.send(502, b'{"code":"QUEUE_UNAVAILABLE"}')
        finally:
            if connection:connection.close()

    def do_OPTIONS(self):self.send(405, b'{}')

class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(*args)
    def process_request(self, request, client_address):
        if not self.slots.acquire(False):return self.shutdown_request(request)
        try:super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise
    def process_request_thread(self, request, client_address):
        try:super().process_request_thread(request, client_address)
        finally:self.slots.release()
    def handle_error(self, request, client_address):pass

if __name__ == '__main__':
    TOKEN = Path('/queue-control/token').read_text().strip()
    if len(TOKEN) < 32:raise RuntimeError('QUEUE_ADMIN_TOKEN_REQUIRED')
    Server(('0.0.0.0', 8080), Handler).serve_forever()
