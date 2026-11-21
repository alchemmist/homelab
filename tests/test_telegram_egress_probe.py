"""Exercise probe errors without sending a packet."""

import runpy
import socket
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

samples = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/telegram-egress-probe.py")
)["samples"]


def test_dns_error():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("resolver", 3)):
        assert list(samples("example.com", None))[0]["stage"] == "dns"


def test_tcp_and_tls_are_distinct():
    address = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
    with (
        patch.dict(samples.__globals__, {"resolve": lambda host: [address, address]}),
        patch("socket.socket") as ctor,
    ):
        sock = ctor.return_value.__enter__.return_value
        ctx = MagicMock()
        sock.connect.side_effect = TimeoutError
        (row,) = samples("example.com", ctx)
        assert row["stage"] == "tcp" and "tls_ms" not in row
        ctx.wrap_socket.assert_not_called()
        sock.connect.side_effect = None
        ctx.wrap_socket.side_effect = TimeoutError
        (row,) = samples("example.com", ctx)
        assert row["stage"] == "tls" and "tcp_ms" in row and "tls_ms" in row
        ctx.wrap_socket.assert_called_with(sock, server_hostname="example.com")
        ctx.wrap_socket.reset_mock()
        ctx.wrap_socket.side_effect = None
        (row,) = samples("example.com", ctx)
        assert row["stage"] == "ok"
        ctx.wrap_socket.assert_called_once_with(sock, server_hostname="example.com")


def test_malformed_resolver_output():
    with patch(
        "subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=b"[")
    ):
        assert list(samples("example.com", None))[0]["stage"] == "dns"


def test_each_distinct_address_is_sampled():
    targets = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
        for ip in ("192.0.2.1", "192.0.2.2")
    ]
    with (
        patch.dict(samples.__globals__, {"resolve": lambda host: targets}),
        patch("socket.socket"),
    ):
        assert [r["ip"] for r in samples("example.com", MagicMock())] == [
            "192.0.2.1",
            "192.0.2.2",
        ]
