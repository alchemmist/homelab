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
    assert checks.main() == 1
    assert {ip for host, ip in called if host == checks.MONORI} == ips
    assert set(json.loads(capsys.readouterr().out)["https"][checks.MONORI]) == ips


@pytest.mark.parametrize(
    "body,expected",
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
def test_wiki_anonymous_contract(monkeypatch, body, expected):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            [], 0, body + b"\n200 application/json", b""
        ),
    )
    assert checks.check(checks.WIKI, "192.0.2.1") == expected


@pytest.mark.parametrize("broken", [False, True])
def test_selfip_requires_all_direct_routes(monkeypatch, broken):
    monkeypatch.setattr(
        checks,
        "check",
        lambda host, ip: (
            "tls-handshake-failed" if broken and host == checks.WIKI else "matched"
        ),
    )
    monkeypatch.setattr(
        checks,
        "observe",
        lambda site, ip, hosts: (
            site,
            {
                h + "/" + p: {"A": [ip], "AAAA": []}
                for h in hosts
                for p in ("tcp", "udp")
            },
        ),
    )
    assert checks.main() == int(broken)


@pytest.mark.parametrize(
    "fault", [None, "same", "cross", "ambiguous", "missing", "unknown"]
)
def test_tls_domain_requires_positive_and_negative_controls(fault):
    from ci.quality.blog_tls_path import correlated

    rows = {
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


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "wrong-realm",
        "registry-open",
        "slash-redirect",
        "ping-drift",
        "anonymous-list",
        "wrong-version",
    ],
)
def test_native_auth_and_slash_boundaries_on_same_peer(monkeypatch, fault):
    results = {
        "/v2/": b'{"errors":[{"code":"UNAUTHORIZED"}]}\n401 application/json\n'
        + checks.CHALLENGE,
        "/v2": b"<title>Harbor</title>\n200 text/html",
        "/api/v2.0/ping": b"Pong\n200 text/plain",
        "/api/version": b'{"Version":"v3.2.1+abc"}\n200 application/json',
        "/api/v1/applications": b'{"code":16,"error":"no session information","message":"no session information"}\n401 application/json',
    }
    cases = {
        "wrong-realm": (
            "/v2/",
            results["/v2/"].replace(b"harbor.socrat", b"other.socrat"),
        ),
        "registry-open": ("/v2/", results["/v2/"].replace(b"401", b"200")),
        "slash-redirect": ("/v2", b"\n301 text/html"),
        "ping-drift": ("/api/v2.0/ping", b"OK\n200 text/plain"),
        "anonymous-list": (
            "/api/v1/applications",
            results["/api/v1/applications"].replace(b"{", b'{"items":[],'),
        ),
        "wrong-version": (
            "/api/version",
            b'{"Version":"unknown"}\n200 application/json',
        ),
    }
    if fault:
        p, value = cases[fault]
        results[p] = value

    def run(args, **kw):
        from urllib.parse import urlsplit

        url = urlsplit(args[-1])
        assert args[args.index("--resolve") + 1] == url.hostname + ":443:192.0.2.1"
        assert ("%header{www-authenticate}" in args[-2]) == (url.path == "/v2/")
        assert "--location" not in args
        return subprocess.CompletedProcess(args, 0, results[url.path], b"")

    monkeypatch.setattr(subprocess, "run", run)
    h = checks.check(checks.HARBOR, "192.0.2.1")
    a = checks.check(checks.ARGO, "192.0.2.1")
    assert (h == "matched") == (
        fault not in ("wrong-realm", "registry-open", "slash-redirect", "ping-drift")
    )
    assert (a == "matched") == (fault not in ("anonymous-list", "wrong-version"))


@pytest.mark.parametrize(
    "change", ["none", "wrong-origin", "relative", "adjacent", "accepted-health"]
)
def test_bot_read_probe_never_follows_oauth_or_sends_a_webhook(monkeypatch, change):
    from ci.quality import socrat_bot_delivery as bot

    seen = []

    def run(args, **kw):
        assert (
            args[:4] == ["curl", "--disable", "--noproxy", "*"]
            and "--location" not in args
            and args[args.index("--resolve") + 1] == bot.HOST + ":443:192.0.2.1"
        )
        seen.append(args[-1])
        loc = {
            "wrong-origin": "https://auth.socrat.alchemmist.xyz.other.invalid/application/o/authorize/?fixture=1",
            "relative": "/application/o/authorize/?fixture=1",
            "adjacent": "https://auth.socrat.alchemmist.xyz/application/o/authorize/else?fixture=1",
        }.get(
            change,
            "https://auth.socrat.alchemmist.xyz/application/o/authorize/?fixture=1",
        )
        data = (
            b"\n302\n" + loc.encode()
            if len(seen) == 1
            else b"404 page not found\n\n404\n"
            if change != "accepted-health"
            else b"ok\n200\n"
        )
        return subprocess.CompletedProcess(args, 0, data, b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert (bot.wire("192.0.2.1") == "matched") == (change == "none")
    assert seen == ["https://" + bot.HOST + p for p in ("/", "/healthz")]


def test_webhook_pin_is_separate_from_three_working_web_paths():
    from ci.quality import socrat_bot_delivery as bot

    ips = {"home": "192.0.2.1", "nl": "192.0.2.2", "moscow": "192.0.2.3"}
    values = {"telegram": {"webhookURL": bot.URL, "webhookIP": ips["nl"]}}
    assert bot.pin(ips, values, (bot.URL, ips["nl"])) == "nl"
    for settings in [(bot.URL, ips["home"]), ("https://other.invalid", ips["nl"])]:
        with pytest.raises(ValueError):
            bot.pin(ips, values, settings)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "wrong-origin",
        "wrong-callback",
        "plain",
        "reused-state",
        "reused-challenge",
        "open-auth",
        "duplicate",
        "extra-scope",
    ],
)
def test_openhands_public_auth_flow_never_follows_or_replays(fault, monkeypatch):
    from urllib.parse import urlencode

    from ci.quality import openhands_public_auth as probe

    calls = []

    def run(args, **kwargs):
        assert (
            "--location" not in args
            and "--insecure" not in args
            and "--cookie" not in args
            and args[:4] == ["curl", "--disable", "--noproxy", "*"]
        )
        assert args[args.index("--resolve") + 1] == probe.HOST + ":443:192.0.2.1"
        calls.append(args[-1])
        n = len(calls)
        base = "https://" + probe.HOST
        if n == 3:
            assert args[-1] == base + "/oauth2/auth"
            return subprocess.CompletedProcess(
                args,
                0,
                b"Unauthorized\n\n"
                + (b"200" if fault == "open-auth" else b"401")
                + b"\n",
                b"",
            )
        assert args[-1] == base + "/"
        params = {
            "response_type": "code",
            "client_id": "fixture",
            "approval_prompt": "auto",
            "scope": "openid profile groups offline_access"
            + (" other" if fault == "extra-scope" else ""),
            "redirect_uri": probe.CALLBACK
            if fault != "wrong-callback"
            else base + "/other",
            "code_challenge_method": "plain" if fault == "plain" else "S256",
            "state": str(1 if fault == "reused-state" else n),
            "code_challenge": ("A" if n == 1 or fault == "reused-challenge" else "B")
            * 43,
        }
        origin = (
            "other.invalid" if fault == "wrong-origin" else "auth.socrat.alchemmist.xyz"
        )
        url = (
            "https://"
            + origin
            + "/application/o/authorize/?"
            + urlencode(params)
            + ("&state=other" if fault == "duplicate" else "")
        )
        return subprocess.CompletedProcess(args, 0, b"\n302\n" + url.encode(), b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert (probe.check("192.0.2.1") == "matched") == (fault is None)


@pytest.mark.parametrize(
    "path,reply,ok",
    [
        ("/api/heartbeat", b'{"ok":true}\n200 application/json', True),
        ("/api/heartbeat", b'{"ok":1}\n200 application/json', False),
        ("/api/heartbeat", b'{"ok":false,"ok":true}\n200 application/json', False),
        (
            "/api/websites",
            b'{"error":{"message":"Unauthorized","code":"unauthorized","status":401}}\n401 application/json',
            True,
        ),
        (
            "/api/websites",
            b'{"error":{"message":"Unauthorized","code":"unauthorized","status":401.0}}\n401 application/json',
            False,
        ),
        ("/api/websites", b"[]\n200 application/json", False),
        ("/script.js", b"fixture\n200 application/javascript; charset=UTF-8", True),
        ("/script.js", b"drift\n200 application/javascript", False),
        ("/script.js", b"fixture\n200 text/html", False),
    ],
)
def test_umami_requires_native_denial_heartbeat_and_reviewed_bytes(
    monkeypatch, path, reply, ok
):
    import hashlib

    monkeypatch.setattr(checks, "UMAMI_SCRIPT", hashlib.sha256(b"fixture").hexdigest())
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0, reply)
    )
    assert (checks._path(checks.UMAMI, "192.0.2.1", path) == "matched") is ok
