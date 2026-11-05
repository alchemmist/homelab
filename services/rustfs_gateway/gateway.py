"""Private bounded artifact reader. No access/request/error bodies are logged.

AUTH_URL must be the trusted Authentik outpost auth/nginx endpoint, never user input.
The outpost must enforce the reviewed owner/platform application policy itself.
"""
import datetime
import hashlib
import hmac
import json
import http.server
import http.client
import socket
import threading
import time
import socketserver
import os
import re
import urllib.error
import urllib.parse
import urllib.request

ORIGIN = 'https://spi-evidence.socrat.alchemmist.xyz'
KEY = re.compile(r'/spi/v1/[0-9a-f]{64}/[0-9a-f]{64}/(?:manifest\.json|E[0-9]{3}-[A-Za-z0-9._-]{1,100})\Z')
MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        if response is not None:
            response.close()
        raise ValueError('redirect denied')


# Absolute elapsed budgets, in addition to individual socket inactivity limits.
HEADER_SECONDS = 15
REQUEST_SECONDS = 45
UPSTREAM_SECONDS = 10
MAX_CONNECTIONS = 8


def expire(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def watchdog(sock, seconds):
    timer = threading.Timer(seconds, expire, (sock,))
    timer.daemon = True
    timer.start()
    return timer


class DeadlineResponse(http.client.HTTPResponse):
    def close(self):
        try:
            super().close()
        finally:
            timer = getattr(self, 'deadline_timer', None)
            if timer is not None:
                timer.cancel()


class DeadlineConnection:
    response_class = DeadlineResponse

    def connect(self):
        start = time.monotonic()
        self.deadline_expired = False
        self.response_owns_deadline = False
        connected_socket = []
        def abort():
            self.deadline_expired = True
            sock = self.sock if self.sock is not None else (connected_socket[0] if connected_socket else None)
            if sock is not None:
                expire(sock)
        self.deadline_timer = threading.Timer(UPSTREAM_SECONDS, abort)
        self.deadline_timer.daemon = True
        self.deadline_timer.start()
        try:
            super().connect()
            connected_socket.append(self.sock)
            if self.deadline_expired or time.monotonic() - start >= UPSTREAM_SECONDS:
                expire(self.sock)
                raise TimeoutError('upstream deadline')
        except BaseException:
            self.close()
            raise

    def getresponse(self):
        # HTTPConnection closes/detaches its socket before returning a response
        # with Connection: close. The response's file still owns the descriptor:
        # keep its watchdog alive until that response is explicitly closed.
        self.transferring_response = True
        try:
            response = super().getresponse()
            response.deadline_timer = self.deadline_timer
            self.response_owns_deadline = True
            return response
        except BaseException:
            self.deadline_timer.cancel()
            raise
        finally:
            self.transferring_response = False

    def close(self):
        timer = getattr(self, 'deadline_timer', None)
        if timer and not (getattr(self, 'transferring_response', False) or
                          getattr(self, 'response_owns_deadline', False)):
            timer.cancel()
        super().close()


class HTTPConnection(DeadlineConnection, http.client.HTTPConnection):
    pass


class HTTPSConnection(DeadlineConnection, http.client.HTTPSConnection):
    pass


class HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(HTTPConnection, request)


class HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(HTTPSConnection, request, context=self._context)


def opener():
    # Environment proxy settings must not redirect private S3/auth traffic.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), HTTPHandler(), HTTPSHandler())


def valid_key(path):
    if not KEY.fullmatch(path) or '..' in path:
        raise ValueError('invalid key')
    return path[1:]


def sign(method, url, access, secret, now=None, region='us-east-1', payload=b''):
    """AWS SigV4, unsigned query unsupported; canonical URI encoded exactly once."""
    u = urllib.parse.urlsplit(url)
    if u.query or u.fragment or u.username or u.password:
        raise ValueError('invalid upstream')
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y%m%dT%H%M%SZ')
    day = stamp[:8]
    digest = hashlib.sha256(payload).hexdigest()
    headers = {'host': u.netloc, 'x-amz-content-sha256': digest, 'x-amz-date': stamp}
    names = ';'.join(sorted(headers))
    canonical = '\n'.join([method, urllib.parse.quote(u.path, safe='/~'), '',
                           ''.join(k + ':' + headers[k] + '\n' for k in sorted(headers)), names, digest])
    scope = day + '/' + region + '/s3/aws4_request'
    message = 'AWS4-HMAC-SHA256\n' + stamp + '\n' + scope + '\n' + hashlib.sha256(canonical.encode()).hexdigest()
    key = ('AWS4' + secret).encode()
    for part in (day, region, 's3', 'aws4_request'):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = 'AWS4-HMAC-SHA256 Credential=' + access + '/' + scope + ', SignedHeaders=' + names + ', Signature=' + signature
    return headers


def bounded(response):
    if response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
        raise ValueError('invalid response')
    length = response.headers.get('Content-Length', '')
    if not length.isascii() or not length.isdigit() or int(length) > MAX_BYTES:
        raise ValueError('invalid length')
    body = response.read(int(length) + 1)
    if len(body) != int(length):
        raise ValueError('length mismatch')
    return body


class Reader:
    def __init__(self):
        self.http = opener()
        self.auth = os.environ['AUTH_URL']
        if self.auth != ORIGIN + '/outpost.goauthentik.io/auth/nginx':
            raise ValueError('invalid auth endpoint')
        self.s3 = os.environ.get('S3_ENDPOINT', 'http://rustfs:9000')
        if self.s3 != 'http://rustfs:9000':
            raise ValueError('fixed S3 service required')
        self.access = os.environ['S3_ACCESS_KEY']
        self.secret = os.environ['S3_SECRET_KEY']

    def authorized(self, cookie):
        if not cookie or len(cookie) > 8192 or '\r' in cookie or '\n' in cookie:
            return False
        request = urllib.request.Request(self.auth, headers={
            'Cookie': cookie, 'X-Original-URL': ORIGIN + '/',
            'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'spi-evidence.socrat.alchemmist.xyz',
            'X-Forwarded-Method': 'GET'})
        try:
            with self.http.open(request, timeout=5) as response:
                groups = set(response.headers.get('X-authentik-groups', '').split('|'))
                return response.status in (200, 204) and bool(groups & {'homelab-owner', 'homelab-platform-operator'})
        except (OSError, ValueError, urllib.error.URLError) as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            return False

    def object(self, key):
        url = self.s3 + '/spi-evidence/' + key
        request = urllib.request.Request(url, headers=sign('GET', url, self.access, self.secret))
        with self.http.open(request, timeout=10) as response:
            return bounded(response)

    def read(self, key):
        valid_key('/' + key)
        prefix, filename = key.rsplit('/', 1)
        event, manifest_hash = prefix.split('/')[-2:]
        manifest = self.object(prefix + '/manifest.json')
        if hashlib.sha256(manifest).hexdigest() != manifest_hash:
            raise ValueError('manifest hash mismatch')
        document = json.loads(manifest.decode('ascii'))
        if not isinstance(document, dict) or document.get('event_key') != event or document.get('format') != 'socrat-evidence-v2':
            raise ValueError('manifest identity mismatch')
        if filename == 'manifest.json':
            return manifest
        rows = document.get('artifacts')
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError('invalid manifest')
        matches = [r for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str) and isinstance(r.get('name'), str) and r['id'] + '-' + r['name'] == filename]
        if len(matches) != 1:
            raise ValueError('unlisted file')
        row = matches[0]
        if type(row.get('stored_chars')) is not int or not 0 <= row['stored_chars'] <= 90000:
            raise ValueError('invalid artifact length')
        body = self.object(key)
        if len(body) != row['stored_chars'] or hashlib.sha256(body).hexdigest() != row.get('sha256'):
            raise ValueError('artifact hash mismatch')
        body.decode('ascii')
        return body


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'ArtifactReader'
    sys_version = ''

    def setup(self):
        self.request.settimeout(HEADER_SECONDS)
        self.header_timer = watchdog(self.request, HEADER_SECONDS)
        self.request_timer = watchdog(self.request, REQUEST_SECONDS)
        super().setup()

    def finish(self):
        try:
            super().finish()
        finally:
            self.header_timer.cancel()
            self.request_timer.cancel()

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.answer()

    def do_HEAD(self):
        self.answer()

    def do_POST(self):
        self.answer()

    do_PUT = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST
    do_PATCH = do_POST

    def answer(self):
        self.close_connection = True
        self.header_timer.cancel()
        # Authentication precedes even validation/error responses; never trust X-auth headers.
        cookies = self.headers.get_all('Cookie', [])
        if len(cookies) != 1 or not self.server.reader.authorized(cookies[0]):
            self.respond(401)
            return
        if self.command not in ('GET', 'HEAD'):
            self.respond(405)
            return
        try:
            raw_target = self.raw_requestline.split()[1].decode('ascii')
            if raw_target != self.path:
                raise ValueError('normalized target denied')
            key = valid_key(raw_target)
        except (ValueError, IndexError):
            self.respond(404)
            return
        try:
            body = self.server.reader.read(key)
        except (OSError, ValueError, urllib.error.URLError) as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            self.respond(502)
            return
        self.respond(200, body, key.rsplit('/', 1)[1])

    def send_error(self, code, message=None, explain=None):
        # Parser/unsupported-method errors must not echo raw request lines or
        # distinguish paths to unauthenticated callers.
        self.close_connection = True
        self.respond(401)

    def respond(self, status, body=b'', filename=None):
        self.send_response(status)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'none'; sandbox")
        self.send_header('Connection', 'close')
        self.send_header('Content-Length', str(len(body)))
        if status == 401:
            self.send_header('Link', '<' + ORIGIN + '/outpost.goauthentik.io/start?rd=https%3A%2F%2Fspi-evidence.socrat.alchemmist.xyz%2F>; rel="authenticate"')
        if filename:
            self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Network resets/timeouts must not emit request context or upstream errors.
        pass


if __name__ == '__main__':
    # Admission is bounded; excess connections are closed without spawning workers.
    server = Server(('0.0.0.0', 8080), Handler)
    server.reader = Reader()
    server.serve_forever()
