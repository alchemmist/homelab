import subprocess

import pytest

from ci.quality import public_advertised_routes as checks


@pytest.mark.parametrize(
    "host,status,body,want",
    [
        (
            checks.BLOG,
            "200 text/html",
            b"<title>Personal blog of Anton Grishin</title>",
            "matched",
        ),
        (checks.BLOG, "200 text/html", b"wrong", "unexpected-application-response"),
        (
            checks.VENICE,
            "401 application/json",
            b'{"detail":"Missing bearer token"}',
            "matched",
        ),
        (
            checks.VENICE,
            "200 application/json",
            b"{}",
            "unexpected-application-response",
        ),
        (checks.VENICE, "401 text/html", b"<html/>", "unexpected-application-response"),
    ],
)
def test_fresh_anonymous_fixed_peer(monkeypatch, host, status, body, want):
    def run(args, **kwargs):
        assert (
            args[:4] == ["curl", "--disable", "--noproxy", "*"]
            and "-k" not in args
            and "--location" not in args
        )
        assert (
            args[args.index("--resolve") + 1] == host + ":443:192.0.2.1"
            and args[-1] == "https://" + host + checks.PATHS[host]
        )
        return subprocess.CompletedProcess(args, 0, body + b"\n" + status.encode(), b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert checks.check(host, "192.0.2.1") == want


def test_no_dns_derived_connection_or_partial_acceptance():
    routes = {"192.0.2.1": "matched", "192.0.2.2": "tls-handshake-failed"}
    good = {"A": ["192.0.2.1"], "AAAA": []}
    bad = {"A": list(routes), "AAAA": []}
    assert checks.verdict(good, good, routes) == "advertised-paths-matched"
    assert checks.verdict(bad, bad, routes) == "advertised-path-not-verified"
    assert checks.verdict(bad, good, routes) == "dns-changed"
    for d in (
        {"A": None, "AAAA": []},
        {"A": [], "AAAA": []},
        {"A": ["192.0.2.1"], "AAAA": None},
        {"A": ["192.0.2.1"], "AAAA": ["::1"]},
        {"A": ["192.0.2.4"], "AAAA": []},
    ):
        assert checks.verdict(d, d, routes) != "advertised-paths-matched"
