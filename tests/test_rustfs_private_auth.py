"""Private Reader failure classification; offline fixtures only."""

import http.client
import threading
import unittest
import urllib.error

from tests.test_rustfs_gateway import BASE, g

OFFLINE_AUTHORIZATION_STATUS = 503
EMPTY_COOKIE_AUTHORIZATION_STATUS = 401


class PrivateAuth(unittest.TestCase):
    """Verify RustFS private auth fails closed for bad tokens."""

    def test_auth_results_are_fail_closed(self) -> None:
        reader = object.__new__(g.Reader)
        reader.auth = g.ORIGIN + "/outpost.goauthentik.io/auth/nginx"

        class HTTP:
            def open(self, *_args, **_kwargs):
                raise self.error

        reader.http = HTTP()
        for code, expected in [(401, 401), (403, 403), (500, 503)]:
            reader.http.error = urllib.error.HTTPError(reader.auth, code, "", {}, None)
            assert reader.authorization("fixture") == expected
        reader.http.error = OSError("offline")
        assert reader.authorization("fixture") == OFFLINE_AUTHORIZATION_STATUS
        assert reader.authorization("") == EMPTY_COOKIE_AUTHORIZATION_STATUS

    def test_denied_and_unavailable_never_loop_or_read(self) -> None:
        class Reader:
            status = 403
            calls = []

            def authorization(self, _cookie):
                return self.status

            def read(self, key):
                self.calls.append(key)
                raise AssertionError("unauthorized object read")

        reader = Reader()
        server = g.http.server.HTTPServer(("127.0.0.1", 0), g.Handler)
        server.reader = reader
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for code in (403, 503):
                reader.status = code
                conn = http.client.HTTPConnection(*server.server_address, timeout=2)
                conn.request(
                    "GET",
                    BASE + "manifest.json",
                    headers={
                        "Host": g.HOST,
                        "Cookie": "fixture",
                        "Accept": "text/html",
                        "X-authentik-groups": "homelab-owner",
                    },
                )
                response = conn.getresponse()
                body = response.read()
                assert response.status == code
                assert response.getheader("Location") is None
                assert response.getheader("Cache-Control") == "no-store"
                assert body == b""
                conn.close()
            assert reader.calls == []
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
