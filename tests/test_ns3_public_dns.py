"""Exact additive delegation contract across every pre-existing health state."""

import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_exact_addition_and_idempotent_delta() -> None:
    """Require one copy of each added record and no retired failover address."""
    zone = load(ROOT / "scripts/public_dns_zone.py", "ns3_zone")
    guard = load(ROOT / "scripts/ns3-public-dns.py", "ns3_guard")

    class Old:
        """Drop the additive ns3 records from an otherwise identical zone."""

        @staticmethod
        def render(*args: object, **kwargs: object):
            return (
                "\n".join(
                    x for x in zone.render(*args, **kwargs).splitlines() if x not in guard.ADDED
                )
                + "\n"
            )

    guard.delta(Old, zone)
    guard.delta(zone, zone)
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        lines = zone.render(123, home_up=home, vps_up=vps).splitlines()
        assert all(lines.count(x) == 1 for x in guard.ADDED)
        for name in zone.FAILOVER:
            assert f"{name} IN A 91.189.82.238" not in lines


def test_guard_rejects_unrelated_records_and_missing_ns3() -> None:
    """Reject an unrelated address and a zone that drops the ns3 glue."""
    zone = load(ROOT / "scripts/public_dns_zone.py", "ns3_zone_negative")
    guard = load(ROOT / "scripts/ns3-public-dns.py", "ns3_guard_negative")

    class Bad:
        """Append one address that is outside the ns3 addition."""

        @staticmethod
        def render(*args: object, **kwargs: object):
            return zone.render(*args, **kwargs) + "unexpected IN A 192.0.2.1\n"

    with pytest.raises(RuntimeError):
        guard.delta(zone, Bad)

    class Missing:
        """Remove the ns3 glue address from the current zone."""

        @staticmethod
        def render(*args: object, **kwargs: object):
            return zone.render(*args, **kwargs).replace("ns3 IN A 91.189.82.238\n", "")

    with pytest.raises(RuntimeError):
        guard.delta(zone, Missing)
