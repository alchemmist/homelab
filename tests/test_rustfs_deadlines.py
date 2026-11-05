"""Real loopback trickle regressions; never contacts deployed services."""
import socket
import threading
import time
import unittest
from unittest.mock import patch
from test_rustfs_gateway import g


class Deadlines(unittest.TestCase):
    def test_trickled_header_and_recovery(self):
        with patch.object(g, 'HEADER_SECONDS', .3):
            server = g.Server(('127.0.0.1', 0), g.Handler)
            t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
            try:
                s = socket.create_connection(server.server_address); s.settimeout(1)
                s.sendall(b'GET / HTTP/1.1\r\nX: ')
                start = time.monotonic()
                for _ in range(12):
                    try: s.sendall(b'a')
                    except OSError: break
                    time.sleep(.05)
                try: self.assertEqual(s.recv(1024), b'')
                except ConnectionResetError: pass
                self.assertLess(time.monotonic()-start, .9)
                s.close()
                with socket.create_connection(server.server_address) as c:
                    c.settimeout(1); c.sendall(b'GET / HTTP/1.0\r\n\r\n')
                    self.assertIn(b'401', c.recv(4096))
            finally:
                server.shutdown(); server.server_close(); t.join()

    def test_trickled_upstream_headers_and_body(self):
        for headers in (True, False):
            with self.subTest(headers=headers), patch.object(g, 'UPSTREAM_SECONDS', .3):
                listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen()
                def peer():
                    c, _ = listener.accept()
                    with c:
                        c.recv(4096)
                        try:
                            if not headers: c.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n')
                            else: c.sendall(b'HTTP/1.1 200 OK\r\nX: ')
                            for _ in range(30):
                                c.sendall(b'a'); time.sleep(.05)
                        except OSError: pass
                t = threading.Thread(target=peer, daemon=True); t.start()
                start = time.monotonic()
                try:
                    with self.assertRaises((OSError, ValueError)):
                        with g.opener().open('http://127.0.0.1:%d/' % listener.getsockname()[1], timeout=1) as response:
                            g.bounded(response)
                    self.assertLess(time.monotonic()-start, .9)
                finally:
                    listener.close(); t.join(2)
