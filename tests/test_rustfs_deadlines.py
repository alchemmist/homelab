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

    def test_connection_close_body_deadline_and_worker_recovery(self):
        for version in ('HTTP/1.1', 'HTTP/1.0'):
            with self.subTest(version=version), patch.object(g, 'UPSTREAM_SECONDS', .25), patch.object(g, 'MAX_CONNECTIONS', 1):
                listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen()
                url = 'http://127.0.0.1:%d/' % listener.getsockname()[1]
                def peer():
                    c, _ = listener.accept()
                    with c:
                        c.recv(4096)
                        try:
                            c.sendall((version + ' 200 OK\r\nConnection: close\r\nContent-Length: 30\r\n\r\n').encode())
                            for _ in range(30):
                                c.sendall(b'a'); time.sleep(.06)
                        except OSError:
                            pass
                t = threading.Thread(target=peer, daemon=True); t.start()
                class Reader:
                    def authorized(self, cookie): return bool(cookie)
                    def read(self, key):
                        with g.opener().open(url, timeout=1) as response:
                            return g.bounded(response)
                server = g.Server(('127.0.0.1', 0), g.Handler); server.reader = Reader()
                serving = threading.Thread(target=server.serve_forever, daemon=True); serving.start()
                try:
                    start = time.monotonic()
                    with socket.create_connection(server.server_address) as c:
                        c.settimeout(1)
                        c.sendall(('GET /spi/v1/' + 'a'*64 + '/' + 'b'*64 + '/manifest.json HTTP/1.0\r\nCookie: fixture\r\n\r\n').encode())
                        self.assertIn(b'502', c.recv(4096))
                    self.assertLess(time.monotonic()-start, .9)
                    # A second connection proves the bounded slot was returned,
                    # not merely that a client-side watchdog closed a socket.
                    until = time.monotonic() + .5
                    while not server.slots.acquire(blocking=False):
                        self.assertLess(time.monotonic(), until); time.sleep(.01)
                    server.slots.release()
                    with socket.create_connection(server.server_address) as c:
                        c.settimeout(1); c.sendall(b'GET / HTTP/1.0\r\n\r\n')
                        self.assertIn(b'401', c.recv(4096))
                finally:
                    listener.close(); t.join(2)
                    server.shutdown(); server.server_close(); serving.join()

    def test_response_close_cancels_upstream_timer(self):
        listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen()
        def peer():
            c, _ = listener.accept()
            with c:
                c.recv(4096)
                c.sendall(b'HTTP/1.0 200 OK\r\nContent-Length: 1\r\n\r\na')
        t = threading.Thread(target=peer, daemon=True); t.start()
        try:
            response = g.opener().open('http://127.0.0.1:%d/' % listener.getsockname()[1], timeout=1)
            timer = response.deadline_timer
            self.assertFalse(timer.finished.is_set())
            self.assertEqual(g.bounded(response), b'a')
            response.close()
            self.assertTrue(timer.finished.is_set())
        finally:
            listener.close(); t.join(2)

    def test_response_write_deadline_releases_worker(self):
        class Handler(g.Handler):
            def setup(self):
                self.request.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
                super().setup()
        class Reader:
            def authorized(self, cookie): return True
            def read(self, key): return b'x' * g.MAX_BYTES
        with patch.object(g, 'REQUEST_SECONDS', .3), patch.object(g, 'MAX_CONNECTIONS', 1):
            server = g.Server(('127.0.0.1', 0), Handler); server.reader = Reader()
            t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
            c = socket.socket(); c.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
            try:
                c.connect(server.server_address)
                c.sendall(('GET /spi/v1/' + 'a'*64 + '/' + 'b'*64 + '/manifest.json HTTP/1.0\r\nCookie: valid\r\n\r\n').encode())
                time.sleep(.6)
                self.assertTrue(server.slots.acquire(blocking=False))
                server.slots.release()
            finally:
                c.close(); server.shutdown(); server.server_close(); t.join()
