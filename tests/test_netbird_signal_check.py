"""Tests for the NetBird signal reachability check script."""

import importlib.util
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "signal_check", ROOT / "scripts/netbird-signal-check.py"
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ProbeState(TypedDict, total=False):
    """Mutable recording of what the fake gRPC channel actually performed."""

    closed: bool
    cancelled: bool
    address: str
    credentials: str
    options: list[tuple[str, object]]
    path: str
    metadata: tuple[tuple[str, str], ...]
    timeout: int
    requests: Iterable[object]


class ProbeTests(unittest.TestCase):
    """Exercise the NetBird signal probe with fake responders."""
    def fake(self, registered=True, fail=False) -> tuple[SimpleNamespace, ProbeState]:
        """Build a fake grpc module and observable call state."""

        class RPCError(Exception):
            def code(self):
                return SimpleNamespace(name="DEADLINE_EXCEEDED")

        state: ProbeState = {"closed": False, "cancelled": False}

        def cancel() -> None:
            state["cancelled"] = True

        def close() -> None:
            state["closed"] = True

        def metadata():
            if fail:
                raise RPCError()
            return [("x-wiretrustee-peer-registered", "1")] if registered else []

        call = SimpleNamespace(
            initial_metadata=metadata,
            code=lambda: SimpleNamespace(name="DEADLINE_EXCEEDED"),
            cancel=cancel,
        )

        def invoke(requests, metadata, timeout):
            state["requests"] = requests
            state["metadata"] = metadata
            state["timeout"] = timeout
            return call

        def stream(path):
            state["path"] = path
            return invoke

        channel = SimpleNamespace(stream_stream=stream, close=close)

        def secure(address, credentials, options):
            state["address"] = address
            state["credentials"] = credentials
            state["options"] = options
            return channel

        return SimpleNamespace(
            RpcError=RPCError,
            secure_channel=secure,
            ssl_channel_credentials=lambda: "trusted-default-roots",
        ), state

    def test_trusted_tls_header_only_stream_and_cleanup(self) -> None:
        """The probe uses trusted TLS, a header-only stream and cleanup."""

        grpc, state = self.fake()
        result = check.probe(check.ENTRANCES[0], grpc_module=grpc)
        assert result["registered_header"]
        assert state["cancelled"]
        assert state["closed"]
        assert state["credentials"] == "trusted-default-roots"
        assert ("grpc.ssl_target_name_override", check.HOST) in state["options"]
        assert state["path"] == "/signalexchange.SignalExchange/ConnectStream"
        assert state["metadata"][0][0] == "x-wiretrustee-peer-id"
        expected_peer_id_length = 44
        assert len(state["metadata"][0][1]) == expected_peer_id_length
        # Finally released the generator; it never yields request DATA.
        assert list(state["requests"]) == []
        assert "metadata" not in result

    def test_missing_header_and_rpc_error_fail_closed_and_release_stream(self) -> None:
        """Missing headers and RPC errors fail closed with the stream released."""

        for registered, fail in [(False, False), (False, True)]:
            grpc, state = self.fake(registered, fail)
            result = check.probe(check.ENTRANCES[0], grpc_module=grpc)
            assert not result["registered_header"]
            assert result["rpc_code"] == "DEADLINE_EXCEEDED"
            assert state["cancelled"]
            assert state["closed"]

    def test_unreviewed_destination_or_unbounded_deadline_refused(self) -> None:
        """Unreviewed destinations and unbounded deadlines are refused."""

        for address, deadline in [
            ("127.0.0.1", 6),
            (check.ENTRANCES[0], 0),
            (check.ENTRANCES[0], 11),
        ]:
            with self.assertRaises(ValueError):
                check.probe(address, deadline)
