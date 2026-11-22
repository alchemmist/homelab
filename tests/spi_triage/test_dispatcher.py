"""Tests for the SPI triage dispatcher."""

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "charts/spi-triage/files"))
from core import Store
from dispatcher import Dispatcher


class DispatchTests(unittest.TestCase):
    """Tests for SPI dispatch decision logic."""

    def setUp(self) -> None:
        """Create a scratch dispatcher store."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name + "/queue.sqlite")

    def enqueue(self, key: str = "a") -> dict[str, object]:
        """Enqueue one event and return its key."""
        job: dict[str, object] = self.store.enqueue({"event_key": key, "episode": key})
        return job

    def test_empty_disabled_and_coalescing(self) -> None:
        """Verify empty, disabled, and coalesced dispatch behavior."""
        calls = []
        d = Dispatcher(self.store, "unused", post=lambda: calls.append(1))
        self.enqueue()
        d.tick()
        assert calls == []
        d.enabled = True
        d.tick()
        d.tick()
        assert calls == [1]
        assert self.store.dispatch_status()["deadline"] > 0

    def test_empty(self) -> None:
        """Verify an empty dispatch ticks without work."""
        d = Dispatcher(self.store, "unused", True, lambda: self.fail("network"))
        assert d.tick() is None

    def test_ambiguous_persists_and_ack_race(self) -> None:
        """Verify ambiguous events persist safely across an ack race."""
        self.enqueue()

        def post() -> None:
            assert self.store.claim()["job_id"] == "a"
            raise TimeoutError

        Dispatcher(self.store, "unused", True, post).tick()
        assert self.store.dispatch_status()["attempts"] == 0
        assert self.store.reserve_dispatch()[0] is None

    def test_deadlines_recovery_and_terminal_lease(self) -> None:
        """Verify deadlines, recovery, and terminal lease transitions."""
        self.enqueue()
        self.enqueue("b")
        self.store.claim()
        self.store.save("a", 4, {}, state="dry_run")
        assert self.store.reserve_dispatch()[0] is not None
        assert self.store.claim()["job_id"] == "b"
        assert self.store.recover_on_start() == 1
        assert self.store.reserve_dispatch()[0] is not None

    def test_backoff_restart_and_due_retry(self) -> None:
        """Verify backoff, restart and due retry scheduling."""
        with (
            patch("core.time.time", return_value=100),
            patch("core.random.uniform", return_value=1),
        ):
            self.enqueue()
            token, deadline = self.store.reserve_dispatch()
            assert deadline == 130
            reopened = Store(self.store.path)
            assert reopened.reserve_dispatch(129) == (None, 130)
            assert reopened.reserve_dispatch(130)[1] == 190
            self.store.claim()
            self.store.fail("a", "INTERNAL_ERROR")
            assert self.store.reserve_dispatch(101) == (None, 160)

    def test_expired_processing_lease(self) -> None:
        """Verify an expired processing lease is reclaimed."""
        with patch("core.time.time", return_value=100):
            self.enqueue()
            self.store.claim()
        assert self.store.reserve_dispatch(2079) == (None, 2080)
        assert self.store.reserve_dispatch(2080)[0] is not None


class ServiceSafetyTests(unittest.TestCase):
    """Tests for dispatcher service safety and lease bounds."""

    def test_expired_lease_while_stage_busy(self) -> None:
        """Verify lease expiry is deferred while the stage is busy."""
        from service import Engine

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp + "/queue.sqlite")
            with patch("core.time.time", return_value=100):
                store.enqueue({"event_key": "a", "episode": "a"})
                store.claim()
            engine = Engine(store, None, None, None)
            calls = []
            dispatcher = Dispatcher(
                store, "unused", True, lambda: calls.append(1), busy=engine.lock.locked
            )
            engine.lock.acquire()
            try:
                assert engine.claim() == {"job_id": ""}
                assert dispatcher.tick() is None
                assert calls == []
                assert store.get("a")["attempts"] == 1
            finally:
                engine.lock.release()
            dispatcher.tick()
            assert calls == [1]
            assert engine.claim() == {"job_id": "a"}

    def test_body_validation_and_partial_timeout(self) -> None:
        """Verify webhook body validation and partial-request timeouts."""
        import socket
        from types import SimpleNamespace

        from core import Failure
        from service import read_request_body

        def check(raw, length, code, shutdown=True) -> None:
            left, right = socket.socketpair()
            try:
                right.sendall(raw)
                if shutdown:
                    right.shutdown(socket.SHUT_WR)
                with left.makefile("rb") as stream:
                    handler = SimpleNamespace(
                        headers={"Content-Length": length},
                        connection=left,
                        rfile=stream,
                    )
                    with self.assertRaises(Failure) as caught:
                        read_request_body(handler, timeout=0.03)
                    assert caught.exception.code == code
                    assert left.gettimeout() is None
            finally:
                left.close()
                right.close()

        check(b"{", "2", "INCOMPLETE_BODY")
        check(b"{", "2", "REQUEST_BODY_TIMEOUT", False)
        check(b"[]", "2", "INVALID_REQUEST")
        check(b"", "-1", "INVALID_BODY_SIZE")
        check(b"", "bad", "INVALID_BODY_SIZE")


class DispatchTransportTests(unittest.TestCase):
    """Tests for dispatch transport interruption handling."""

    def test_trickling_headers_are_interrupted_without_body_read(self) -> None:
        """Verify trickling-header requests abort without reading bodies."""
        import http.client
        import socket
        import threading

        class Connection:
            def __init__(self, *args, **kwargs) -> None:
                self.sock, self.peer = socket.socketpair()
                self.closed = False

            def connect(self) -> None:
                pass

            def request(self, *args, **kwargs) -> None:
                pass

            def getresponse(self) -> None:
                # Simulates a parser waiting indefinitely for complete headers.
                self.sock.recv(1)
                raise http.client.RemoteDisconnected()

            def close(self) -> None:
                self.closed = True
                self.sock.close()
                self.peer.close()

        connection = Connection()
        real_timer = threading.Timer
        with (
            patch("dispatcher.http.client.HTTPConnection", return_value=connection),
            patch(
                "dispatcher.threading.Timer",
                side_effect=lambda seconds, callback: real_timer(0.02, callback),
            ),
            self.assertRaises(http.client.RemoteDisconnected),
        ):
            Dispatcher(None, "unused")._post()
        assert connection.closed


if __name__ == "__main__":
    unittest.main()
