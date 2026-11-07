"""Private Reader failure classification; offline fixtures only."""
import http.client
import threading
import unittest
import urllib.error
from test_rustfs_gateway import g, BASE


class PrivateAuth(unittest.TestCase):
    def test_auth_results_are_fail_closed(self):
        reader = object.__new__(g.Reader)
        reader.auth = g.ORIGIN + '/outpost.goauthentik.io/auth/nginx'
        class HTTP:
            def open(self, *args, **kwargs):
                raise self.error
        reader.http = HTTP()
        for code, expected in [(401, 401), (403, 403), (500, 503)]:
            reader.http.error = urllib.error.HTTPError(reader.auth, code, '', {}, None)
            self.assertEqual(reader.authorization('fixture'), expected)
        reader.http.error = OSError('offline')
        self.assertEqual(reader.authorization('fixture'), 503)
        self.assertEqual(reader.authorization(''), 401)

    def test_denied_and_unavailable_never_loop_or_read(self):
        class Reader:
            status = 403
            calls = []
            def authorization(self, cookie): return self.status
            def read(self, key): self.calls.append(key); raise AssertionError('unauthorized object read')
        reader = Reader()
        server = g.http.server.HTTPServer(('127.0.0.1', 0), g.Handler)
        server.reader = reader
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            for code in (403, 503):
                reader.status = code
                conn = http.client.HTTPConnection(*server.server_address, timeout=2)
                conn.request('GET', BASE+'manifest.json', headers={
                    'Host': g.HOST, 'Cookie': 'fixture', 'Accept': 'text/html',
                    'X-authentik-groups': 'homelab-owner'})
                response = conn.getresponse(); body = response.read()
                self.assertEqual(response.status, code)
                self.assertIsNone(response.getheader('Location'))
                self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                self.assertEqual(body, b''); conn.close()
            self.assertEqual(reader.calls, [])
        finally:
            server.shutdown(); server.server_close(); worker.join()
