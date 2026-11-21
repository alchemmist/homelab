"""Check scoped internal DNS preservation without applying cluster changes."""

import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    "observer_dns", Path(__file__).parents[1] / "scripts/observer-internal-dns.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def before():
    """Test before behavior."""
    return {
        "metadata": {"uid": "owned", "resourceVersion": "123"},
        "data": {"rancher-private.server": "keep exact"},
    }


def test_exact_scoped_key_and_preservation() -> None:
    """Require the owned key to be added without replacing preserved data."""
    original = before()
    result = m.desired(original, "10.43.218.222")
    assert result["rancher-private.server"] == "keep exact"
    assert original == before()
    assert "auth.socrat.alchemmist.xyz:53" in result[m.KEY]
    assert "fallthrough" in result[m.KEY]  # preserve subdomain/TXT resolution
    assert "forward . /etc/resolv.conf" in result[m.KEY]
    assert len(result) == 2


def test_collision_stops() -> None:
    """Require a foreign owned key to stop before any replacement."""
    original = before()
    original["data"][m.KEY] = "foreign"
    with pytest.raises(RuntimeError):
        m.desired(original, "10.43.218.222")


def test_same_key_acceptance() -> None:
    """Require an already-owned key with the same zone to be accepted."""
    original = before()
    original["data"][m.KEY] = m.zone("10.43.218.222")
    assert m.desired(original, "10.43.218.222") == original["data"]


def test_cas_guards_and_no_wholesale_replacement() -> None:
    """Require CAS tests before an add of only the owned key."""
    original = before()
    p = m.patch(original, m.desired(original, "10.43.218.222"))
    assert [x["path"] for x in p[:3]] == ["/metadata/uid", "/metadata/resourceVersion", "/data"]
    assert all(x["op"] == "test" for x in p[:3])
    assert p[3]["op"] == "add" and p[3]["path"] == "/data/" + m.KEY


@pytest.mark.parametrize("address", ["109.120.141.97", "109.173.40.247", "::1", "bad"])
def test_refuse_public_or_invalid(address) -> None:
    """Require public, IPv6, and invalid addresses to be refused."""
    with pytest.raises(ValueError):
        m.zone(address)


def test_replace_only_our_previous_owned_value() -> None:
    """Require replacement only when the previous owned value matches."""
    original = before()
    original["data"][m.KEY] = m.zone("10.43.218.222")
    result = m.desired(original, m.INTERNAL_VIP, owned_value=original["data"][m.KEY])
    assert result[m.KEY] == m.zone("192.168.0.250")
    assert result["rancher-private.server"] == original["data"]["rancher-private.server"]
    with pytest.raises(RuntimeError):
        m.desired(original, m.INTERNAL_VIP, owned_value="not-ours")
