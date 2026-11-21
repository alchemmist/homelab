"""Exact additive delegation contract across every pre-existing health state."""

import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def render_text(zone, *args: object) -> str:
    rendered = zone.render(*args)
    if not isinstance(rendered, str):
        raise TypeError(f"zone.render returned {type(rendered).__name__}, expected str")
    return rendered


def test_exact_addition_and_idempotent_delta() -> None:
    """Require one copy of each added record and no retired failover address."""
    zone = load(ROOT / "scripts/public_dns_zone.py", "ns3_zone")
    guard = load(ROOT / "scripts/ns3-public-dns.py", "ns3_guard")

    class Old:
        """Drop the additive ns3 records from an otherwise identical zone."""

        @staticmethod
        def render(*args: object) -> str:
            rendered = render_text(zone, *args)
            kept = [line for line in rendered.splitlines() if line not in guard.ADDED]
            return "\n".join(kept) + "\n"

    guard.delta(Old, zone)
    guard.delta(zone, zone)
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        lines = zone.render(123, home, vps).splitlines()
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
        def render(*args: object) -> str:
            return render_text(zone, *args) + "unexpected IN A 192.0.2.1\n"

    with pytest.raises(RuntimeError):
        guard.delta(zone, Bad)

    class Missing:
        """Remove the ns3 glue address from the current zone."""

        @staticmethod
        def render(*args: object) -> str:
            return render_text(zone, *args).replace("ns3 IN A 91.189.82.238\n", "")

    with pytest.raises(RuntimeError):
        guard.delta(zone, Missing)
