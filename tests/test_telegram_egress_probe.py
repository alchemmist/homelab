"""Exercise probe errors without sending a packet."""

import runpy
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

samples = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/telegram-egress-probe.py")
)["samples"]


def test_dns_error():
    with patch("socket.getaddrinfo", side_effect=socket.gaierror):
        assert list(samples("example.com", None))[0]["stage"] == "dns"


def test_tcp_and_tls_are_distinct():
    address = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
    with (
        patch("socket.getaddrinfo", return_value=[address, address]),
        patch("socket.socket") as ctor,
    ):
        sock = ctor.return_value.__enter__.return_value
        ctx = MagicMock()
        sock.connect.side_effect = TimeoutError
        (row,) = samples("example.com", ctx)
        assert row["stage"] == "tcp"
        ctx.wrap_socket.assert_not_called()
        sock.connect.side_effect = None
        ctx.wrap_socket.side_effect = TimeoutError
        (row,) = samples("example.com", ctx)
        assert row["stage"] == "tls"
        ctx.wrap_socket.assert_called_with(sock, server_hostname="example.com")
        ctx.wrap_socket.side_effect = None
        (row,) = samples("example.com", ctx)
        assert row["stage"] == "ok"
