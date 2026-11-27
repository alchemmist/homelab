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
        (
            checks.MONORI,
            "401 application/json",
            b'{"detail":"Not authenticated"}',
            "matched",
        ),
        (
            checks.MONORI,
            "401 application/json",
            b'{"detail":"Missing bearer token"}',
            "unexpected-application-response",
        ),
        (
            checks.MONORI,
            "200 application/json",
            b"{}",
            "unexpected-application-response",
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


def test_legacy_home_only_dns_must_not_skip_direct_monori_checks(monkeypatch, capsys):
    import json

    import yaml

    ips = {
        v["publicIP"]
        for v in yaml.safe_load(checks.CATALOG.read_text())["replicas"].values()
    }
    called = []
    monkeypatch.setattr(
        checks, "check", lambda host, ip: called.append((host, ip)) or "matched"
    )
    monkeypatch.setattr(
        checks,
        "observe",
        lambda site, ip, hosts: (
            site,
            {
                h + "/" + p: {"A": ["109.173.40.247"], "AAAA": []}
                for h in hosts
                for p in ("tcp", "udp")
            },
        ),
    )
    assert checks.main() == 0
    assert {ip for host, ip in called if host == checks.MONORI} == ips
    assert set(json.loads(capsys.readouterr().out)["https"][checks.MONORI]) == ips
