import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "public_dns_zone.py"
spec = importlib.util.spec_from_file_location("public_dns_zone", SCRIPT)
zone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zone)


def test_both_entrances_stay_published_while_both_are_healthy():
    text = zone.render(1, True, True)
    assert text.count("chat IN A %s" % zone.HOME) == 1
    assert text.count("chat IN A %s" % zone.VPS) == 1
    assert "mail IN A %s" % zone.HOME in text
    assert "mail IN A %s" % zone.VPS not in text


def test_home_failure_leaves_only_the_vps_on_failover_names():
    text = zone.render(2, False, True)
    assert "llm IN A %s" % zone.VPS in text
    assert "llm IN A %s" % zone.HOME not in text
    assert "ns1 IN A %s" % zone.HOME in text
    assert "sync IN A %s" % zone.HOME in text


def test_netbird_and_existing_bot_survive_renderer_deploys_and_follow_health():
    for home_up, vps_up in [(True, True), (False, True), (True, False), (False, False)]:
        text = zone.render(3, home_up, vps_up)
        expected = zone.healthy_addresses(home_up, vps_up)
        for name in ["netbird.socrat", "bot.socrat"]:
            for address in [zone.HOME, zone.VPS]:
                assert (f"{name} IN A {address}" in text) == (address in expected)
    assert zone.FAILOVER.count("netbird.socrat") == 1


def test_independent_vps_relay_never_points_to_home():
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        text = zone.render(4, home, vps)
        assert f"netbird-relay-vps.socrat IN A {zone.VPS}" in text
        assert f"netbird-relay-vps.socrat IN A {zone.HOME}" not in text


def test_total_probe_failure_keeps_both_addresses():
    assert zone.healthy_addresses(False, False) == [zone.HOME, zone.VPS]


def test_rustfs_names_additive_without_changes_to_existing_records():
    import subprocess
    original = subprocess.check_output(['git', 'show', 'cde1027:scripts/public_dns_zone.py'], text=True)
    prior = {}
    exec(compile(original, 'prior_public_dns_zone.py', 'exec'), prior)
    for home, vps in [(True, True), (False, True), (True, False), (False, False)]:
        new = zone.render(123, home, vps).splitlines()
        names = ('rustfs.socrat IN A ', 'spi-evidence.socrat IN A ')
        assert [line for line in new if not line.startswith(names)] == prior['render'](123, home, vps).splitlines()
        for name in ('rustfs.socrat', 'spi-evidence.socrat'):
            for address in zone.healthy_addresses(home, vps):
                assert new.count(f'{name} IN A {address}') == 1
