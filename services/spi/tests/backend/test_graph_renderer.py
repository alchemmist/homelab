import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from graph_contract import GraphError, canonical, resolve
from graph_gateway import Server, secret
from graph_renderer import Renderer
from test_graph_contract import graph, png


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.raw = png()
        self.request = resolve(
            graph(),
            {"service": "api"},
            starts_at="2026-11-08T12:00:00Z",
            observed_at="2026-11-08T12:02:00Z",
        )
        self.calls = []

    def wire(self, path, seconds):
        self.calls.append((path, seconds))
        return 200, "image/png", self.raw

    def renderer(self, **kw):
        return Renderer(
            "private-test-token",
            {"service-health:12": ["service"]},
            transport=kw.pop("transport", self.wire),
            **kw,
        )

    def test_render_and_cache(self):
        engine = self.renderer()
        body, meta = engine.render(self.request, caller="telegram", seconds=4)
        assert body == self.raw
        assert json.loads(meta)["sha256"] == hashlib.sha256(body).hexdigest()
        assert engine.render(self.request, caller="spi", seconds=20) == (body, meta)
        assert len(self.calls) == 1
        assert "private" not in self.calls[0][0]

    def test_cache_expiry(self):
        now = [0]
        engine = self.renderer(clock=lambda: now[0])
        engine.render(self.request, caller="spi", seconds=20)
        now[0] = 3601
        engine.render(self.request, caller="spi", seconds=20)
        assert len(self.calls) == 2

    def test_policy_and_digest_before_network(self):
        for key, value in [("panel_id", 13), ("digest", "fake"), ("version", True)]:
            req = {**self.request, key: value}
            if key == "panel_id":
                req["digest"] = hashlib.sha256(
                    canonical({k: v for k, v in req.items() if k != "digest"}).encode()
                ).hexdigest()
            with self.subTest(key=key), pytest.raises(GraphError):
                self.renderer().render(req, caller="spi", seconds=20)
        assert self.calls == []

    def test_invalid_upstreams_never_cached(self):
        for response in [
            (302, "image/png", self.raw),
            (200, "text/html", b"login"),
            (200, "image/png", b"not a png"),
        ]:
            engine = self.renderer(transport=lambda *args: response)
            for _ in range(2):
                with pytest.raises(GraphError):
                    engine.render(self.request, caller="spi", seconds=20)
            assert not engine._cache

    def test_total_deadline(self):
        now = [0]

        def slow(*args):
            now[0] += 21
            return 200, "image/png", self.raw

        engine = self.renderer(transport=slow, clock=lambda: now[0])
        with pytest.raises(GraphError, match="RENDER_TIMEOUT"):
            engine.render(self.request, caller="spi", seconds=20)
        assert not engine._cache
        assert not engine._inflight

    def test_spi_cannot_consume_telegram_reserved_slot(self):
        started, release = threading.Event(), threading.Event()

        def blocking(*args):
            self.calls.append(args)
            if len(self.calls) == 1:
                started.set()
                release.wait(3)
            return 200, "image/png", self.raw

        engine = self.renderer(transport=blocking)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(engine.render, self.request, caller="spi", seconds=20)
            try:
                assert started.wait(2)
                other = dict(self.request, mode="resolved")
                other["digest"] = hashlib.sha256(
                    canonical({k: v for k, v in other.items() if k != "digest"}).encode()
                ).hexdigest()
                with pytest.raises(GraphError, match="BUSY"):
                    engine.render(other, caller="spi", seconds=20)
                assert engine.render(other, caller="telegram", seconds=4)[0] == self.raw
                assert not first.done()
                release.set()
                first.result(timeout=3)
            finally:
                release.set()

    def test_single_flight(self):
        started, release, follower = threading.Event(), threading.Event(), threading.Event()

        def blocking(*args):
            self.calls.append(args)
            started.set()
            release.wait(3)
            return 200, "image/png", self.raw

        engine = self.renderer(transport=blocking)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(engine.render, self.request, caller="spi", seconds=20)
            assert started.wait(2)

            def follow():
                follower.set()
                return engine.render(self.request, caller="telegram", seconds=4)

            second = pool.submit(follow)
            assert follower.wait(2)
            release.set()
            assert first.result(timeout=3) == second.result(timeout=3)
        assert len(self.calls) == 1

    def test_gateway_auth_and_exact_png(self):
        server = Server(
            ("127.0.0.1", 0), self.renderer(), {"telegram": "test-tg", "spi": "test-spi"}
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def post(auth, raw=None, path="/v1/render"):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            try:
                connection.request(
                    "POST",
                    path,
                    body=raw or canonical(self.request),
                    headers={"Authorization": auth, "Content-Type": "application/json"},
                )
                r = connection.getresponse()
                return r.status, dict(r.getheaders()), r.read()
            finally:
                connection.close()

        try:
            assert post("Bearer wrong")[0] == 401
            assert post("Bearer test-tg", "{}")[0] == 422
            status, headers, body = post("Bearer test-tg")
            assert status == 200
            assert body == self.raw
            assert headers["X-Content-SHA256"] == hashlib.sha256(body).hexdigest()
            assert headers["Cache-Control"] == "no-store"
            primary = {
                "annotation": canonical(
                    {"version": 1, "graphs": [graph(), graph(id="context", panel_id=13)]}
                ),
                "labels": {"service": "api"},
                "starts_at": "2026-11-08T12:00:00Z",
                "observed_at": "2026-11-08T12:02:00Z",
                "ends_at": None,
                "status": "firing",
            }
            status, headers, body = post("Bearer test-tg", canonical(primary), "/v1/primary")
            assert status == 200
            assert body == self.raw
            assert headers["X-Graph-Mode"] == "onset"
            assert headers["X-Render-Digest"] == self.request["digest"]
            assert len(self.calls) == 1  # second graph isn't the primary
            assert (
                post("Bearer test-tg", canonical({**primary, "labels": {}}), "/v1/primary")[0]
                == 422
            )
            assert (
                post(
                    "Bearer test-tg",
                    canonical({**primary, "url": "https://invalid.example"}),
                    "/v1/primary",
                )[0]
                == 422
            )

        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)

    def test_primary_gateway_allows_realistic_telegram_render_time(self):
        """A 4.5-second render failed under the old 4s gateway budget, not under 15s."""
        now = [0.0]
        budgets = []

        def slow(path, seconds):
            budgets.append(seconds)
            now[0] += 4.5  # deterministic clock, no slow sleep or production I/O
            return 200, "image/png", self.raw

        engine = self.renderer(transport=slow, clock=lambda: now[0])
        server = Server(("127.0.0.1", 0), engine, {"telegram": "test-tg", "spi": "test-spi"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        payload = {
            "annotation": canonical({"version": 1, "graphs": [graph()]}),
            "labels": {"service": "api"},
            "starts_at": "2026-11-08T12:00:00Z",
            "observed_at": "2026-11-08T12:02:00Z",
            "ends_at": None,
            "status": "firing",
        }
        try:
            connection.request(
                "POST",
                "/v1/primary",
                body=canonical(payload),
                headers={"Authorization": "Bearer test-tg", "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            assert response.status == 200
            assert response.read() == self.raw
            assert budgets == [15]
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(3)

    def test_secret_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text("synthetic-token-only")
            path.chmod(0o600)
            assert secret(path) == "synthetic-token-only"
            path.chmod(0o644)
            with pytest.raises(ValueError):
                secret(path)


if __name__ == "__main__":
    unittest.main()
