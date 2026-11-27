"""Offline checks for single-entrance DNS acceptance and inventory coverage."""

import sys

import pytest
import yaml

from ci.quality import public_survivors as audit


def test_all_route_owners_have_three_cases() -> None:
    """Report exclusions, reserved names and separate VPN paths rather than dropping them."""
    catalog = yaml.safe_load(audit.CATALOG.read_text())
    rows = audit.cases(catalog)
    assert len(rows) == 3 * sum(len(hosts) for hosts in catalog["hosts"].values())
    assert rows["monori", "monori.alchemmist.xyz", "nl"] == "unverified"
    assert rows["traefik-edge", "vpn.alchemmist.xyz", "home"] == "dedicated VPN path"
    assert rows["schoolbot", "bot.sch1357.ru", "moscow"] == "reserved"
    for ns in ("socrat-home", "rustfs"):
        assert rows[ns, "socrat.alchemmist.xyz", "moscow"] == "unverified"


@pytest.mark.parametrize(
    "answers,code",
    [
        ({audit.ENTRIES["moscow"]}, 0),
        (set(audit.ENTRIES.values()), 1),
        ({audit.ENTRIES["moscow"], "::1"}, 1),
        (set(), 1),
    ],
)
def test_dns_requires_only_survivor(monkeypatch, answers: set[str], code: int) -> None:
    """A dead second address, IPv6 alternative or empty result cannot pass this gate."""
    monkeypatch.setattr(
        sys, "argv", ["audit", "--dns", "blog", "alchemmist.xyz", "moscow"]
    )
    monkeypatch.setattr(audit, "dns_view", lambda host: answers)
    assert audit.main() == code


def test_reserved_case_is_not_queried(monkeypatch, capsys) -> None:
    """A known but unpublished case is a usage error, not a failed DNS lookup."""
    monkeypatch.setattr(
        sys, "argv", ["audit", "--dns", "schoolbot", "bot.sch1357.ru", "home"]
    )
    monkeypatch.setattr(
        audit, "dns_view", lambda host: pytest.fail("unexpected DNS lookup")
    )
    with pytest.raises(SystemExit) as exc:
        audit.main()
    assert exc.value.code == 2
    assert "not eligible for a DNS check: reserved" in capsys.readouterr().err


@pytest.mark.parametrize("entry", ["home", "nl", "moscow"])
def test_schoolbot_external_authority_is_not_a_self_ip_case(monkeypatch, entry):
    """Even a HOME-only client match must not certify DNS we do not publish."""
    from ci.quality.public_web import replica_values

    catalog = yaml.safe_load(audit.CATALOG.read_text())
    host = "inform.sch1357.ru"
    assert audit.cases(catalog)["schoolbot", host, entry] == "external DNS; not a self-IP case"
    values = replica_values(catalog, catalog["replicas"][entry], 42)
    assert host in values["publications"]["schoolbot"]
    assert "sch1357.ru" not in values["zoneFile"]
    monkeypatch.setattr(sys, "argv", ["audit", "--dns", "schoolbot", host, entry])
    monkeypatch.setattr(audit, "dns_view", lambda _: pytest.fail("unexpected lookup"))
    with pytest.raises(SystemExit) as exc:
        audit.main()
    assert exc.value.code == 2


def test_unknown_survivor_lists_valid_entries(monkeypatch, capsys) -> None:
    """Explain survivor spelling errors before attempting a lookup."""
    monkeypatch.setattr(
        sys, "argv", ["audit", "--dns", "blog", "alchemmist.xyz", "nl-only"]
    )
    with pytest.raises(SystemExit) as exc:
        audit.main()
    assert exc.value.code == 2
    message, _, choices = capsys.readouterr().err.strip().rpartition("; choose from ")
    assert "Unknown survivor 'nl-only'" in message
    assert set(choices.split(", ")) == set(audit.ENTRIES)


@pytest.mark.parametrize(
    ("status", "ct", "body", "valid"),
    [
        (200, "application/json; charset=utf-8", b'{"ok":true}', True),
        (302, "application/json", b'{"ok":true}', False),
        (200, "text/html", b'{"ok":true}', False),
        (200, "application/json", b'{"ok":1}', False),
        (200, "application/json", b'{"ok":false,"ok":true}', False),
        (200, "application/json", b'{"ok":true}' + b" " * 8192, False),
    ],
)
def test_schoolbot_anonymous_payload(status, ct, body, valid):
    from ci.quality.schoolbot_entry_health import healthy

    assert healthy(status, ct, body) is valid


def test_closed_schoolbot_probe_only_uses_loopback(monkeypatch, tmp_path):
    from ci.quality import schoolbot_entry_health as health

    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump({"hosts": {"schoolbot": {health.HOST: {"dns": "external"}}}})
    )
    monkeypatch.setattr(health, "CATALOG", catalog)
    calls = []
    monkeypatch.setattr(
        health,
        "probe",
        lambda ip, port: calls.append((ip, port)) or "tls-verification-failed-18",
    )
    monkeypatch.setattr(sys, "argv", ["health", "--local-port", "10443"])
    assert health.main() == 1 and calls == [("127.0.0.1", 10443)]


@pytest.mark.parametrize(("length", "ok"), [(11, True), (12, False), (100000, False)])
def test_schoolbot_body_must_match_advertised_length(length, ok):
    import http.client
    import io
    from unittest.mock import Mock

    from ci.quality.schoolbot_entry_health import response_healthy

    sock = Mock()
    sock.makefile.return_value = io.BytesIO(
        f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {length}\r\n\r\n".encode()
        + b'{"ok":true}'
    )
    with http.client.HTTPResponse(sock) as response:
        response.begin()
        assert response_healthy(response) is ok


def test_no_length_short_read_does_not_hide_following_body():
    from unittest.mock import Mock

    from ci.quality.schoolbot_entry_health import response_healthy

    response = Mock(status=200)
    response.getheader.side_effect = lambda name, default=None: (
        "application/json" if name == "Content-Type" else default
    )
    response.read.side_effect = [b'{"ok":true}', b"x"]
    assert not response_healthy(response)


@pytest.mark.parametrize("bad", ["null", "hosts: []", "hosts: {schoolbot: {}}"])
def test_missing_schoolbot_policy_is_a_cli_error(monkeypatch, tmp_path, bad):
    from ci.quality import schoolbot_entry_health as health

    f = tmp_path / "catalog.yaml"
    f.write_text(bad)
    monkeypatch.setattr(health, "CATALOG", f)
    monkeypatch.setattr(sys, "argv", ["health", "--public"])
    with pytest.raises(SystemExit) as e:
        health.main()
    assert e.value.code == 2
