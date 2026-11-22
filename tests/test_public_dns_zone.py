"""Tests for the public DNS zone management script."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "public_dns_zone.py"
spec = importlib.util.spec_from_file_location("public_dns_zone", SCRIPT)
zone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zone)


def test_both_entrances_stay_published_while_both_are_healthy() -> None:
    text = zone.render(1, True, True)
    assert text.count("chat IN A %s" % zone.HOME) == 1
    assert text.count("chat IN A %s" % zone.VPS) == 1
    assert "mail IN A %s" % zone.HOME in text
    assert "mail IN A %s" % zone.VPS not in text


def test_home_failure_leaves_only_the_vps_on_failover_names() -> None:
    text = zone.render(2, False, True)
    assert "llm IN A %s" % zone.VPS in text
    assert "llm IN A %s" % zone.HOME not in text
    assert "ns1 IN A %s" % zone.HOME in text
    assert "sync IN A %s" % zone.HOME in text


def test_netbird_and_existing_bot_survive_renderer_deploys_and_follow_health() -> None:
    for home_up, vps_up in [(True, True), (False, True), (True, False), (False, False)]:
        text = zone.render(3, home_up, vps_up)
        expected = zone.healthy_addresses(home_up, vps_up)
        for name in ["netbird.socrat", "bot.socrat"]:
            for address in [zone.HOME, zone.VPS]:
                assert (f"{name} IN A {address}" in text) == (address in expected)
    assert zone.FAILOVER.count("netbird.socrat") == 1


def test_independent_vps_relay_never_points_to_home() -> None:
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        text = zone.render(4, home, vps)
        assert f"netbird-relay-vps.socrat IN A {zone.VPS}" in text
        assert f"netbird-relay-vps.socrat IN A {zone.HOME}" not in text


def test_total_probe_failure_keeps_both_addresses() -> None:
    assert zone.healthy_addresses(False, False) == [zone.HOME, zone.VPS]


def _reviewed_openhands_addition(lines: list[str], addresses: list[str]) -> list[str]:
    """Validate the entire reviewed additive delta, retaining all unrelated lines."""
    prefix = "openhands.socrat IN A "
    assert [line for line in lines if line.startswith(prefix)] == [
        prefix + address for address in addresses
    ]
    return [line for line in lines if not line.startswith(prefix)]


@pytest.mark.parametrize(
    "records",
    [[], ["192.0.2.1"], ["192.0.2.1", "203.0.113.1"], ["192.0.2.1", "192.0.2.2", "192.0.2.2"]],
)
def test_reviewed_addition_refuses_missing_wrong_or_duplicate_records(records: list[str]) -> None:
    """The new name cannot be excluded from history until its exact full delta passes."""
    lines = ["openhands.socrat IN A " + address for address in records]
    with pytest.raises(AssertionError):
        _reviewed_openhands_addition(lines, ["192.0.2.1", "192.0.2.2"])


def test_rustfs_names_additive_without_changes_to_existing_records() -> None:
    import subprocess

    original = subprocess.check_output(
        ["git", "show", "cde1027:scripts/public_dns_zone.py"], text=True
    )
    prior = {}
    exec(compile(original, "prior_public_dns_zone.py", "exec"), prior)
    # The additive-name contract is independent of the approved VPS IP migration.
    # Normalize only that address in the historical fixture; compare all records.
    prior["VPS"] = zone.VPS
    prior["STATIC_A"]["netbird-relay-vps.socrat"] = [zone.VPS]
    # Independently approved VPN-only Moscow cutover; do not normalize other names.
    prior["FAILOVER"].remove("vpn")
    prior["STATIC_A"]["vpn"] = ["91.189.82.238"]
    for home, vps in [(True, True), (False, True), (True, False), (False, False)]:
        new = zone.render(123, home, vps).splitlines()
        # Require the exact reviewed new records before the unchanged historical comparison.
        new = _reviewed_openhands_addition(new, zone.healthy_addresses(home, vps))
        # Independently approved concurrent SPI DNS addition is also historical-fixture scope.
        names = (
            "rustfs.socrat IN A ",
            "spi-evidence.socrat IN A ",
            "kuma.socrat IN A ",
            "tv IN A ",
            "spi.socrat IN A ",
            "wishlist IN A ",
            "venice.socrat IN A ",
            "password.socrat IN A ",
        )
        # Monori alone has a separately tested primary/standby publication policy.
        historical = prior["render"](123, home, vps).splitlines()
        assert [x for x in new if x.startswith("monori IN A ")] == [
            "monori IN A " + ip for ip in zone.monori_addresses(home, vps)
        ]
        assert [
            line
            for line in new
            if not line.startswith((*names, "monori IN A "))
            and line not in ("@ IN NS ns3.alchemmist.xyz.", "ns3 IN A 91.189.82.238")
        ] == [x for x in historical if not x.startswith("monori IN A ")]
        for name in ("rustfs.socrat", "spi-evidence.socrat"):
            for address in zone.healthy_addresses(home, vps):
                assert new.count(f"{name} IN A {address}") == 1


def test_current_vps_address_after_provider_migration() -> None:
    assert zone.VPS == "109.120.141.60"


def test_kuma_administration_name_follows_both_reviewed_entrances() -> None:
    for home, vps in [(True, True), (False, True), (True, False), (False, False)]:
        text = zone.render(7, home, vps)
        for ip in [zone.HOME, zone.VPS]:
            assert (f"kuma.socrat IN A {ip}" in text) == (ip in zone.healthy_addresses(home, vps))


def test_retired_tv_alias_is_not_rendered() -> None:
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        assert "tv IN A " not in zone.render(8, home, vps)


def test_vpn_has_only_moscow_even_when_original_entrances_fail() -> None:
    assert "vpn" not in zone.FAILOVER
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        lines = zone.render(123, home, vps).splitlines()
        assert [line for line in lines if line.startswith("vpn IN A ")] == [
            "vpn IN A 91.189.82.238"
        ]
        assert "ns1 IN A 109.173.40.247" in lines
        assert "ns2 IN A 109.120.141.60" in lines


@pytest.mark.parametrize("home,vps,ips", [(True, True, [zone.HOME]), (True, False, [zone.HOME]),
    (False, True, [zone.VPS]), (False, False, [zone.HOME, zone.VPS])])
def test_monori_https_selection_is_scoped(home, vps, ips):
    lines = zone.render(123, True, True, monori_health=(home, vps)).splitlines()
    assert [x for x in lines if x.startswith("monori IN A ")] == ["monori IN A " + ip for ip in ips]
    assert [x for x in lines if x.startswith("lms IN A ")] == ["lms IN A " + ip for ip in (zone.HOME, zone.VPS)]


@pytest.mark.parametrize("rc,status,healthy", [(0, "200", True), (0, "503", False), (60, "000", False)])
def test_monori_https_requires_verified_exchange(monkeypatch, rc, status, healthy):
    import subprocess

    def run(argv, **kwargs):
        assert argv[argv.index("--resolve") + 1] == "monori.alchemmist.xyz:8443:127.0.0.1"
        assert argv[-1] == "https://monori.alchemmist.xyz:8443/"
        assert argv[argv.index("--max-time") + 1] == "3"
        assert "--insecure" not in argv and "-k" not in argv
        assert kwargs["timeout"] == 3.5
        return subprocess.CompletedProcess(argv, rc, stdout=status)

    monkeypatch.setattr(zone.subprocess, "run", run)
    assert zone.monori_https("127.0.0.1", 8443, 3) is healthy
