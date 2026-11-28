"""Offline loopback contract; never submit operator input, credentials or saved tests."""

import http.client
import io
import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import socket

import pytest

from ci.quality.closed_formatter_action import matches, probe

FORMAT_PORT = 1234
EXPECTED_HEADERS = {"Host", "Content-Type", "Accept", "Accept-Encoding", "Connection"}
EXPECTED_HOST = "fq.alchemmist.xyz"


class Wire:
    """A minimal file-backed stand-in for the parser's bound socket."""

    def __init__(self, data: bytes) -> None:
        """Keep the raw wire bytes for makefile()."""
        self.data = data

    def makefile(self, *_: object) -> io.BytesIO:
        """Return the saved bytes as the response byte stream."""
        return io.BytesIO(self.data)


def response(body: bytes, headers: bytes = b"", status: int = 200) -> http.client.HTTPResponse:
    """Drive the real http parser over a canned response stream."""
    raw = f"HTTP/1.1 {status} status\r\n".encode() + headers + b"\r\n" + body
    # The parser only needs a makefile-backed object; HTTPResponse itself is typed
    # against the bounding socket class, so this is the single trusted seam.
    wire = cast("socket.socket", Wire(raw))
    r = http.client.HTTPResponse(wire)
    r.begin()
    return r


def test_exact_json_and_framing() -> None:
    hdr = b"Content-Type: application/json\r\n"
    body = b'{"formatted":"result"}'
    expected: dict[str, object] = {"formatted": "result"}
    assert matches(response(body, hdr), 200, expected)
    for r in (
        response(body, hdr, 302),
        response(body),
        response(body, hdr + b"Content-Length: 100\r\n"),
        response(body, hdr + b"Content-Length: 999999\r\n"),
        response(body + b" " * 2048, hdr),
        response(b'{"formatted":"wrong","formatted":"result"}', hdr),
        response(b'{"formatted":"result","extra":0}', hdr),
        response(b'{"formatted":"echo"}', hdr),
    ):
        assert not matches(r, 200, expected)


def test_only_fixed_loopback_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class Connection:
        """A monkeypatched HTTPConnection that pins every fixed request."""

        def __init__(self, host: str, port: int, timeout: object) -> None:
            """Pin the strict loopback binding used by the formatter probe."""
            assert host == "127.0.0.1"
            assert port == FORMAT_PORT
            assert isinstance(timeout, int)
            assert timeout > 0

        def request(
            self,
            method: str,
            path: str,
            body: bytes,
            headers: dict[str, str],
        ) -> None:
            """Pin the request shape and record the submitted payload."""
            assert (method, path) == ("POST", "/api/format")
            assert headers["Host"] == EXPECTED_HOST
            assert set(headers) == EXPECTED_HEADERS
            payload = json.loads(body)
            calls.append(payload)

        def getresponse(self) -> http.client.HTTPResponse:
            """Return the two pinned, distinct formatted results."""
            value = ["int value = 1;\n", "int other = 2;\n"][len(calls) - 1]
            return response(
                json.dumps({"formatted": value}).encode(),
                b"Content-Type: application/json\r\n",
            )

        def close(self) -> None:
            """No teardown side effects needed for the fake connection."""

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    assert probe(FORMAT_PORT)
    assert calls == [
        {"code": c, "formatter": "clang-format", "config": "BasedOnStyle: LLVM\n"}
        for c in ("int   value=1;\n", "int   other=2;\n")
    ]
    for invalid in (-1, 0, 65536, True):
        with pytest.raises(ValueError, match=r"invalid loopback port$"):
            probe(invalid)
