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


def test_total_probe_failure_keeps_both_addresses():
    assert zone.healthy_addresses(False, False) == [zone.HOME, zone.VPS]
