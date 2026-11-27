"""Advertised-route bracketing: only fixed peers, never DNS-learned destinations."""

import subprocess
from collections.abc import Sequence

import pytest
import yaml

from ci.quality import public_advertised_routes as checks
from ci.quality.public_web import CATALOG


@pytest.mark.parametrize(
    ("host", "status", "body", "want"),
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
def test_fresh_anonymous_fixed_peer(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
    status: str,
    body: bytes,
    want: str,
) -> None:
    def run(args: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert list(args)[:4] == ["curl", "--disable", "--noproxy", "*"]
        assert "-k" not in args
        assert "--location" not in args
        assert args[args.index("--resolve") + 1] == host + ":443:192.0.2.1"
        assert args[-1] == "https://" + host + checks.PATHS[host]
        return subprocess.CompletedProcess(args, 0, body.decode() + "\n" + status, "")

    monkeypatch.setattr(subprocess, "run", run)
    assert checks.check(host, "192.0.2.1") == want


def test_no_dns_derived_connection_or_partial_acceptance() -> None:
    routes = {"192.0.2.1": "matched", "192.0.2.2": "tls-handshake-failed"}
    good: dict[str, object] = {"A": ["192.0.2.1"], "AAAA": []}
    bad: dict[str, object] = {"A": list(routes), "AAAA": []}
    assert checks.verdict(good, good, routes) == "advertised-paths-matched"
    assert checks.verdict(bad, bad, routes) == "advertised-path-not-verified"
    assert checks.verdict(bad, good, routes) == "dns-changed"
    strainers: tuple[dict[str, object], ...] = (
        {"A": None, "AAAA": []},
        {"A": [], "AAAA": []},
        {"A": ["192.0.2.1"], "AAAA": None},
        {"A": ["192.0.2.1"], "AAAA": ["::1"]},
        {"A": ["192.0.2.4"], "AAAA": []},
    )
    for strained in strainers:
        assert checks.verdict(strained, strained, routes) != "advertised-paths-matched"


def test_legacy_home_only_dns_must_not_skip_direct_monori_checks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    catalog: object = yaml.safe_load(CATALOG.read_text())
    assert isinstance(catalog, dict)
    replicas: object = catalog["replicas"]
    assert isinstance(replicas, dict)
    ips: set[object] = set()
    for replica in replicas.values():
        assert isinstance(replica, dict)
        ips.add(replica["publicIP"])
    called: list[tuple[str, str]] = []

    def check_stub(host: str, ip: str) -> str:
        called.append((host, ip))
        return "matched"

    monkeypatch.setattr(checks, "check", check_stub)
    monkeypatch.setattr(
        checks,
        "observe",
        lambda site, _ip, hosts: (
            site,
            {
                h + "/" + p: {"A": ["109.173.40.247"], "AAAA": []}
                for h in hosts
                for p in ("tcp", "udp")
            },
        ),
    )
    assert checks.main() == 1
    assert {ip for host, ip in called if host == checks.MONORI} == ips
    assert set(json.loads(capsys.readouterr().out)["https"][checks.MONORI]) == ips


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b'{"user":null,"writable":false,"bootstrap_required":false}', "matched"),
        (
            b'{"user":null,"writable":0,"bootstrap_required":false}',
            "unexpected-application-response",
        ),
        (
            b'{"writable":false,"bootstrap_required":false}',
            "unexpected-application-response",
        ),
        (
            b'{"user":null,"writable":true,"writable":false,"bootstrap_required":false}',
            "unexpected-application-response",
        ),
    ],
)
def test_wiki_anonymous_contract(
    monkeypatch: pytest.MonkeyPatch, body: bytes, expected: str
) -> None:
    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        payload = body.decode() + "\n200 application/json"
        return subprocess.CompletedProcess(["curl"], 0, payload, "")

    monkeypatch.setattr(subprocess, "run", run)
    assert checks.check(checks.WIKI, "192.0.2.1") == expected


@pytest.mark.parametrize("broken", [False, True])
def test_selfip_requires_all_direct_routes(
    monkeypatch: pytest.MonkeyPatch, *, broken: bool
) -> None:
    monkeypatch.setattr(
        checks,
        "check",
        lambda host, _ip: "tls-handshake-failed" if broken and host == checks.WIKI else "matched",
    )
    monkeypatch.setattr(
        checks,
        "observe",
        lambda site, ip, hosts: (
            site,
            {h + "/" + p: {"A": [ip], "AAAA": []} for h in hosts for p in ("tcp", "udp")},
        ),
    )
    assert checks.main() == int(broken)


@pytest.mark.parametrize("fault", [None, "same", "cross", "ambiguous", "missing", "unknown"])
def test_tls_domain_requires_positive_and_negative_controls(fault: None | str) -> None:
    from ci.quality.blog_tls_path import correlated

    rows: dict[str, dict[str, str]] = {
        "a": {"a": "resumed", "b": "full-handshake"},
        "b": {"a": "full-handshake", "b": "resumed"},
        "s": {"a": "resumed", "b": "full-handshake"},
    }
    if fault == "same":
        rows["a"]["a"] = "full-handshake"
    elif fault == "cross":
        rows["a"]["b"] = "resumed"
    elif fault == "ambiguous":
        rows["s"]["b"] = "resumed"
    elif fault == "missing":
        del rows["s"]["a"]
    elif fault == "unknown":
        rows["s"]["b"] = "unverified"
    assert correlated(rows, ["a", "b"], ["s"]) == ({} if fault else {"s": "a"})
