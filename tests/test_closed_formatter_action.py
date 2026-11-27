"""Offline loopback contract; never submit operator input, credentials or saved tests."""

import http.client
import io
import json

import pytest

from ci.quality.closed_formatter_action import matches, probe


class Wire:
    def __init__(self, data):
        self.data = data

    def makefile(self, *_):
        return io.BytesIO(self.data)


def response(body, headers=b"", status=200):
    r = http.client.HTTPResponse(
        Wire(f"HTTP/1.1 {status} status\r\n".encode() + headers + b"\r\n" + body)
    )
    r.begin()
    return r


def test_exact_json_and_framing():
    hdr = b"Content-Type: application/json\r\n"
    body = b'{"formatted":"result"}'
    expected = {"formatted": "result"}
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


def test_only_fixed_loopback_actions(monkeypatch):
    calls = []

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("127.0.0.1", 1234) and timeout > 0

        def request(self, method, path, body, headers):
            assert (method, path) == ("POST", "/api/format")
            assert headers["Host"] == "fq.alchemmist.xyz" and set(headers) == {
                "Host",
                "Content-Type",
                "Accept",
                "Accept-Encoding",
                "Connection",
            }
            payload = json.loads(body)
            calls.append(payload)

        def getresponse(self):
            value = ["int value = 1;\n", "int other = 2;\n"][len(calls) - 1]
            return response(
                json.dumps({"formatted": value}).encode(),
                b"Content-Type: application/json\r\n",
            )

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    assert probe(1234)
    assert calls == [
        {"code": c, "formatter": "clang-format", "config": "BasedOnStyle: LLVM\n"}
        for c in ("int   value=1;\n", "int   other=2;\n")
    ]
    for invalid in (-1, 0, 65536, True):
        with pytest.raises(ValueError):
            probe(invalid)
