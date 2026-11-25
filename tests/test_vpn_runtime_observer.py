"""Tests for scripts/vpn-runtime-observer.py."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "runtime_observer", ROOT / "ansible/scripts/vpn-runtime-observer.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_relay_latch_is_not_sufficient_and_split_brain_unknown() -> None:
    """Test behavior for test_relay_latch_is_not_sufficient_and_split_brain_unknown."""
    p = m.PROFILES["socrat-4"]

    def state(mode: str, agent: bool, native: bool, marker: bool) -> dict[str, object]:
        return {
            "mode": mode,
            "agent_active": agent,
            "native_active": native,
            "fallback_marker": marker,
        }

    assert (
        m.classify(
            p, state("kubernetes", True, False, False), agent=True, native=[False], marker=False
        )
        == 0
    )
    assert (
        m.classify(p, state("native", False, True, True), agent=False, native=[True], marker=True)
        == 1
    )
    assert (
        m.classify(p, state("native", True, True, True), agent=True, native=[True], marker=True)
        == -1
    )
    assert (
        m.classify(p, state("native", False, False, True), agent=False, native=[False], marker=True)
        == -1
    )
    assert (
        m.classify(
            p, state("kubernetes", True, False, False), agent=False, native=[False], marker=False
        )
        == -1
    )
    assert (
        m.classify(
            p,
            state("transition-to-native", False, False, True),
            agent=False,
            native=[False],
            marker=True,
        )
        == -1
    )


def test_backend_requires_native_both_units_and_server_ownership() -> None:
    """Test behavior for test_backend_requires_native_both_units_and_server_ownership."""
    p = m.PROFILES["socrat-2"]
    assert (
        m.classify(p, {"mode": "kubernetes"}, agent=True, native=[False, False], marker=False) == 0
    )
    assert m.classify(p, {"mode": "fallback"}, agent=False, native=[True, True], marker=True) == 1
    assert m.classify(p, {"mode": "fallback"}, agent=False, native=[True, False], marker=True) == -1
    assert m.classify(p, {"mode": "fallback"}, agent=True, native=[True, True], marker=True) == -1


def test_socket_observation_does_not_call_established_sessions_off(
    tmp_path: Path,
) -> None:
    """Test behavior for test_socket_observation_does_not_call_established_sessions_off."""
    net = tmp_path / "net"
    net.mkdir()
    for name in ["tcp", "tcp6", "udp", "udp6"]:
        (net / name).write_text("header\n")
    (net / "tcp").write_text("header\n0: 00000000:7D35 00000000:0000 01\n")
    assert m.listening(tmp_path, "tcp") == {32053}
    (net / "udp6").write_text("header\n0: 00000000:7D55 00000000:0000 07\n")
    assert m.listening(tmp_path, "udp") == {32085}


def test_export_is_atomic_numeric_no_accounts_or_paths(tmp_path: Path) -> None:
    """Test behavior for test_export_is_atomic_numeric_no_accounts_or_paths."""
    p = tmp_path / "vpn-runtime.prom"
    m.write_metrics(
        p,
        "relay",
        {
            "runtime": 0,
            "check_success": 1,
            "off": 0,
            "observation_success": 1,
            "observed_timestamp_seconds": 123,
        },
    )
    text = p.read_text()
    assert 'runtime{component="relay"} 0' in text
    assert p.stat().st_mode & 0o777 == 0o644
    assert len(list(tmp_path.iterdir())) == 1
    assert "email" not in text
    assert "token" not in text


def test_observer_has_no_recovery_or_mutating_command() -> None:
    """Test behavior for test_observer_has_no_recovery_or_mutating_command."""
    s = (ROOT / "ansible/scripts/vpn-runtime-observer.py").read_text()
    for forbidden in [
        "'tick'",
        "'activate'",
        "'failback'",
        "'demote'",
        "'start'",
        "'stop'",
        "'restart'",
        "'kubectl'",
        "'nft'",
    ]:
        assert forbidden not in s


def test_moscow_reuses_actual_watchdog_observation_without_more_tls_or_lock(
    tmp_path: Path,
) -> None:
    """Test behavior for test_moscow_reuses_actual_watchdog_observation_without_more_tls_or_lock."""
    from types import SimpleNamespace

    profile = dict(m.PROFILES["socrat-4"], marker=str(tmp_path / "fallback.active"))
    (tmp_path / "state.json").write_text(json.dumps({"mode": "kubernetes", "healthy": True}))
    net = tmp_path / "net"
    net.mkdir()
    for name in ["tcp", "tcp6", "udp", "udp6"]:
        (net / name).write_text("header\n")
    (net / "tcp").write_text("header\n0: 00000000:01BB 00000000:0000 0A\n")

    def run(args: list[str], _timeout=30) -> object:
        assert args[:2] == ["systemctl", "show"]
        return SimpleNamespace(
            returncode=0,
            stdout="Id=k3s-agent.service\nLoadState=loaded\nActiveState=active\n\nId=homelab-vpn-transit-native.service\nLoadState=loaded\nActiveState=inactive\n",
        )

    with patch.object(m, "command", side_effect=run):
        out = m.observe(profile, proc=tmp_path)
    assert out["runtime"] == 0
    assert out["check_success"] == 1
    assert out["off"] == 0
    assert out["observed_timestamp_seconds"] == (tmp_path / "state.json").stat().st_mtime
