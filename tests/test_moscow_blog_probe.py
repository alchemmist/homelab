"""Offline contracts for the private HTTPS acceptance client."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/check-moscow-private-blog.py"
SPEC = importlib.util.spec_from_file_location("moscow_blog_probe", PATH)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


@pytest.mark.parametrize(
    "value", ["91.189.82.238", "alchemmist.xyz", "127.0.0.1", "10.250.0.40"]
)
def test_no_public_or_host_fallback(value: str) -> None:
    """The client only accepts the private Service address supplied by the operator."""
    with pytest.raises(ValueError):
        PROBE.service_ip(value)


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, PROBE.TITLE, True),
        (302, PROBE.TITLE, False),
        (200, b"default backend", False),
    ],
)
@pytest.mark.parametrize(
    "host", ["www.alchemmist.xyz", "cats.alchemmist.xyz", "fq.alchemmist.xyz"]
)
def test_probe_contract(status: int, body: bytes, expected: bool, host: str) -> None:
    """Preserve the requested hostname for SNI and HTTP while dialing the private IP."""
    if body == PROBE.TITLE:
        body = PROBE.TITLES[host]
    with (
        patch.object(PROBE.socket, "create_connection") as dial,
        patch.object(PROBE.ssl, "create_default_context") as context,
        patch.object(PROBE.http.client, "HTTPResponse") as response,
    ):
        reply = response.return_value.__enter__.return_value
        reply.status = status
        reply.read.return_value = body
        assert PROBE.probe(host, "10.43.1.2") is expected
        dial.assert_called_once_with(("10.43.1.2", 443), timeout=5)
        wrap = context.return_value.wrap_socket
        wrap.assert_called_once_with(
            dial.return_value.__enter__.return_value, server_hostname=host
        )
        assert (
            f"Host: {host}\r\n".encode("ascii")
            in wrap.return_value.__enter__.return_value.sendall.call_args.args[0]
        )
