"""Tests for SPI triage evidence upload to S3."""

import datetime
import hashlib
import sys
import socket
import threading
import time
import unittest
from typing import Protocol
from typing import cast
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "charts/spi-triage/files"))
import s3_evidence as s

KEY = "spi/v1/" + "a" * 64 + "/" + "b" * 64 + "/E001-test.json"


class S3ClientHandle(Protocol):
    """Duck-type of s3_evidence.S3Evidence used by these transport tests."""

    def ensure_object(self, key: str, body: object) -> dict[str, object]:
        """Upload an object under a public key with readback verification."""
        ...


class ClientTests(unittest.TestCase):
    """Tests for the S3 evidence client."""

    def client(self, responses: list[object]) -> S3ClientHandle:
        'Build an S3 client with scripted responses.'
        self.calls: list[tuple[str, str, dict[str, object], bytes]] = []


        def transport(*args: object) -> object:
            self.calls.append(cast("tuple[str, str, dict[str, object], bytes]", args))
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        result: S3ClientHandle = s.S3Evidence("access", "secret", transport=transport)
        return result

    def test_resolver_capacity_survives_sequential_timeouts(self) -> None:
        'Verify the resolver capacity survives sequential timeouts.'
        release = threading.Event()
        workers = []
        slots = threading.BoundedSemaphore(s.MAX_RESOLVERS)


        def stuck(*_args, **_kwargs) -> list[tuple[int, int, int, str, tuple[str, int]]]:
            workers.append(threading.current_thread())
            release.wait()
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 9))]

        with (
            patch.object(s, "_RESOLVER_SLOTS", slots),
            patch.object(s.socket, "getaddrinfo", stuck),
            patch.object(s.socket, "socket") as make_socket,
        ):
            try:
                for _ in range(24):
                    conn = s.HTTPConnection("unused.invalid", 9000, timeout=0.01)
                    conn.budget = 0.01
                    with self.assertRaises(TimeoutError):
                        conn.connect()
                    conn.close()
                assert len(workers) == s.MAX_RESOLVERS
                assert all(worker.is_alive() for worker in workers)
            finally:
                release.set()
                for worker in workers:
                    worker.join(1)
            assert all(not worker.is_alive() for worker in workers)
            make_socket.assert_not_called()
            # All slots are returned on actual completion, not caller timeout.
            for _ in range(s.MAX_RESOLVERS):
                assert slots.acquire(blocking=False)
            assert not slots.acquire(blocking=False)

    def test_existing(self) -> None:
        'Verify existing objects are fetched unchanged.'
        c = self.client([(200, {}, b"abc")])
        assert c.ensure_object(KEY, b"abc")["verified"]
        assert len(self.calls) == 1

    def test_private_bucket_qualified_paths_unchanged(self) -> None:
        'Verify private bucket paths are not rewritten.'
        for key in (KEY, KEY.rsplit("/", 1)[0] + "/manifest.json"):
            c = self.client([(404, {}, b""), (201, {}, b""), (200, {}, b"abc")])
            receipt = c.ensure_object(key, b"abc")
            assert [call[0] for call in self.calls] == ["GET", "PUT", "GET"]
            assert [call[1] for call in self.calls] == ["/spi-evidence/" + key] * 3
            assert receipt["bucket"] == "spi-evidence"
            assert receipt["key"] == key
            assert receipt["sha256"] == hashlib.sha256(b"abc").hexdigest()

    def test_conflict(self) -> None:
        'Verify mismatched objects are reported as conflicts.'
        c = self.client([(200, {}, b"bad")])
        with self.assertRaises(s.StorageConflict):
            c.ensure_object(KEY, b"abc")
        assert len(self.calls) == 1

    def test_conditional_and_races(self) -> None:
        'Verify conditional writes behave under race responses.'
        for status in (200, 201, 204, 409, 412):
            c = self.client([(404, {}, b""), (status, {}, b""), (200, {}, b"abc")])
            c.ensure_object(KEY, b"abc")
            assert self.calls[1][2]["If-None-Match"] == "*"
            assert self.calls[1][3] == b"abc"

    def test_ambiguous_recovery(self) -> None:
        'Verify ambiguous failures recover safely on retry.'
        c = self.client([(404, {}, b""), TimeoutError(), (200, {}, b"abc"), (200, {}, b"abc")])
        c.ensure_object(KEY, b"abc")
        c.ensure_object(KEY, b"abc")
        assert [x[0] for x in self.calls] == ["GET", "PUT", "GET", "GET"]

    def test_status(self) -> None:
        'Verify retryable statuses are mapped correctly.'
        for status in (408, 429, 500, 503):
            c = self.client([(status, {"Retry-After": "12"}, b"")])
            with self.assertRaises(s.StorageTransient) as ctx:
                c.ensure_object(KEY, b"abc")
            hint_seconds = 12
            assert ctx.exception.retry_after == hint_seconds
        for status in (301, 403, 401):
            with self.assertRaises(s.StoragePermanent):
                self.client([(status, {}, b"")]).ensure_object(KEY, b"abc")

    def test_validation(self) -> None:
        'Verify origin validation rejects bad hosts and schemes.'
        for origin in ("http://localhost", s.ORIGIN + "/", s.ORIGIN + "?x=1"):
            with self.assertRaises(s.StoragePermanent):
                s.S3Evidence("a", "b", origin=origin)
        for key in (KEY.upper(), KEY + "?a", KEY.replace("test", ".."), "/" + KEY):
            with self.assertRaises(s.StoragePermanent):
                self.client([]).ensure_object(key, b"")
        for body in ("abc", bytearray(b"a"), b"x" * (s.MAX_BYTES + 1)):
            with self.assertRaises(s.StoragePermanent):
                self.client([]).ensure_object(KEY, body)

    def test_readback(self) -> None:
        'Verify read-backs validate the written content.'
        for body, error in (
            (b"bad", s.StorageConflict),
            (b"x" * (s.MAX_BYTES + 1), s.StoragePermanent),
        ):
            with self.assertRaises(error):
                self.client([(404, {}, b""), (200, {}, b""), (200, {}, body)]).ensure_object(
                    KEY, b"abc"
                )

    def test_retry_date(self) -> None:
        'Verify retry-after HTTP dates are honored.'
        date = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=50)
        ).strftime("%a, %d %b %Y %H:%M:%S GMT")
        # The Retry-After date minus parser clock skew lands within ~48-50 seconds.
        retry_floor_seconds = 48
        retry_ceiling_seconds = 50
        assert retry_floor_seconds <= s.retry_after(date) <= retry_ceiling_seconds
        # Retry hints from dates are capped at one day.
        retry_hint_cap = 86400
        assert s.retry_after("999999999") == retry_hint_cap
        assert s.retry_after("invalid") is None

    def test_signing(self) -> None:
        'Verify request signatures match the canonical form.'
        now = datetime.datetime(2025, 1, 2, tzinfo=datetime.timezone.utc)
        h = s.sign(
            "PUT",
            s.ORIGIN + "/spi-evidence/" + KEY,
            "access",
            "secret",
            now=now,
            payload=b"\x00\xff",
        )
        assert h["x-amz-content-sha256"] == hashlib.sha256(b"\x00\xff").hexdigest()
        assert h["host"] == "rustfs.rustfs.svc.cluster.local:9000"
        assert "20250102/us-east-1/s3/aws4_request" in h["Authorization"]
        assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in h["Authorization"]
        # Independent reference implementation already used by private gateway.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gateway", Path(__file__).resolve().parents[2] / "services/rustfs_gateway/gateway.py"
        )
        gateway = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gateway)
        assert h == gateway.sign(
            "PUT",
            s.ORIGIN + "/spi-evidence/" + KEY,
            "access",
            "secret",
            now=now,
            payload=b"\x00\xff",
        )

    def test_close_body_deadline_and_cleanup(self) -> None:
        'Verify body closes under deadline and cleans up sockets.'
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()

        def serve() -> None:
            conn, _ = listener.accept()
            with conn:
                conn.recv(8192)
                conn.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
                try:
                    for _ in range(100):
                        conn.sendall(b"x")
                        time.sleep(0.02)
                except OSError:
                    pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        conn = s.HTTPConnection("127.0.0.1", listener.getsockname()[1], timeout=1)
        conn.budget = 0.15
        start = time.monotonic()
        conn.request("GET", "/")
        response = conn.getresponse()
        assert conn.deadline_timer.is_alive()
        try:
            try:
                response.read(1000)
            except OSError:
                pass
        finally:
            response.close()
            conn.close()
            listener.close()
        # A full request/response round trip must stay well under a second.
        request_deadline_seconds = 0.8
        assert time.monotonic() - start < request_deadline_seconds
        conn.deadline_timer.join(0.3)
        assert not conn.deadline_timer.is_alive()


if __name__ == "__main__":
    unittest.main()
