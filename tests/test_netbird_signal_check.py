import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "signal_check", ROOT / "scripts/netbird-signal-check.py"
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ProbeTests(unittest.TestCase):
    def fake(self, registered=True, fail=False):
        class RPCError(Exception):
            def code(self):
                return SimpleNamespace(name="DEADLINE_EXCEEDED")

        state = {"closed": False, "cancelled": False}

        def metadata():
            if fail:
                raise RPCError()
            return [("x-wiretrustee-peer-registered", "1")] if registered else []

        call = SimpleNamespace(
            initial_metadata=metadata,
            code=lambda: SimpleNamespace(name="DEADLINE_EXCEEDED"),
            cancel=lambda: state.update(cancelled=True),
        )

        def invoke(requests, **kwargs):
            state.update(requests=requests, **kwargs)
            return call

        def stream(path):
            state["path"] = path
            return invoke

        channel = SimpleNamespace(stream_stream=stream, close=lambda: state.update(closed=True))

        def secure(address, credentials, options):
            state.update(address=address, credentials=credentials, options=options)
            return channel

        return SimpleNamespace(
            RpcError=RPCError,
            secure_channel=secure,
            ssl_channel_credentials=lambda: "trusted-default-roots",
        ), state

    def test_trusted_tls_header_only_stream_and_cleanup(self):
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

    def test_missing_header_and_rpc_error_fail_closed_and_release_stream(self):
        for registered, fail in [(False, False), (False, True)]:
            grpc, state = self.fake(registered, fail)
            result = check.probe(check.ENTRANCES[0], grpc_module=grpc)
            assert not result["registered_header"]
            assert result["rpc_code"] == "DEADLINE_EXCEEDED"
            assert state["cancelled"]
            assert state["closed"]

    def test_unreviewed_destination_or_unbounded_deadline_refused(self):
        for address, deadline in [
            ("127.0.0.1", 6),
            (check.ENTRANCES[0], 0),
            (check.ENTRANCES[0], 11),
        ]:
            with self.assertRaises(ValueError):
                check.probe(address, deadline)
