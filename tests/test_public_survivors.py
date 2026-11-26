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
    assert rows["monori", "monori.alchemmist.xyz", "nl"] == "policy exclusion"
    assert rows["traefik-edge", "vpn.alchemmist.xyz", "home"] == "no VPN entrance"
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


def test_unknown_survivor_lists_valid_entries(monkeypatch, capsys) -> None:
    """Explain survivor spelling errors before attempting a lookup."""
    monkeypatch.setattr(
        sys, "argv", ["audit", "--dns", "blog", "alchemmist.xyz", "nl-only"]
    )
    with pytest.raises(SystemExit) as exc:
        audit.main()
    assert exc.value.code == 2
    assert (
        "Unknown survivor 'nl-only'; choose from home, nl, moscow"
        in capsys.readouterr().err
    )
