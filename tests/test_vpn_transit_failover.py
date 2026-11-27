"""Check VPN transit failover decisions, image bytes, and source contracts."""

import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tarfile
from types import ModuleType
from typing import Protocol, Self

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def module(name: str) -> ModuleType:
    """Test behavior for module."""
    s = importlib.util.spec_from_file_location(
        name, ROOT / "ansible/scripts" / f"{name}.py"
    )
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


class TransitController(Protocol):
    """Static surface of the dynamically loaded transit failover controller."""

    marker: pathlib.Path
    state: dict[str, object]
    last_probe: dict[str, object]

    def tick(self) -> None: ...

    def save(
        self,
        mode: str,
        boot_id: str = "",
        grace_until: int = 0,
        failures: int = 0,
        healthy: bool = False,
    ) -> None: ...

    def healthy(self) -> bool: ...

    def activate(self, why: str) -> None: ...

    def promote(self) -> None: ...

    def demote(self) -> None: ...

    def failback(self) -> None: ...

    def recovery_scope(self) -> dict[str, object]: ...


@pytest.fixture
def ctl(tmp_path, monkeypatch) -> tuple[ModuleType, TransitController]:
    """Test behavior for ctl."""
    m = module("vpn-transit-failover")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ws_path": "/test"}))
    monkeypatch.setattr(m, "CONFIG", p)
    return m, m.Controller()


def test_no_api_only_failover_and_failure_threshold(ctl, monkeypatch) -> None:
    """Test behavior for test_no_api_only_failover_and_failure_threshold."""
    m, c = ctl
    monkeypatch.setattr(m, "boot_id", lambda: "test-boot")
    c.save(mode="kubernetes", boot_id="test-boot", grace_until=0)
    monkeypatch.setattr(
        c,
        "recovery_scope",
        lambda: {"recover_local": True, "scope": "local-listener-failed"},
    )
    calls = []
    monkeypatch.setattr(c, "healthy", lambda: False)
    monkeypatch.setattr(c, "activate", calls.append)
    for _ in range(3):
        c.tick()
    assert calls == []
    c.tick()
    assert len(calls) == 1
    monkeypatch.setattr(c, "healthy", lambda: True)
    c.tick()
    assert c.state["failures"] == 0
    assert c.state["grace_until"] == 0


def test_prepared_and_native_are_sticky(ctl, monkeypatch) -> None:
    """Test behavior for test_prepared_and_native_are_sticky."""
    m, c = ctl
    calls = []
    monkeypatch.setattr(c, "activate", calls.append)
    c.tick()
    assert calls == []
    m.atomic(c.marker, {"native": True})
    c.save(mode="native")
    monkeypatch.setattr(m, "active", lambda _: True)
    monkeypatch.setattr(c, "healthy", lambda: True)
    c.tick()
    assert c.state["mode"] == "native"
    assert c.state["healthy"]
    assert calls == []


def test_uncertain_transition_never_replays(ctl) -> None:
    """Test behavior for test_uncertain_transition_never_replays."""
    _m, c = ctl
    c.save(mode="transition-to-kubernetes")
    with pytest.raises(RuntimeError, match="Uncertain"):
        c.tick()


def test_unknown_port_owner_blocks_native_start(ctl, monkeypatch) -> None:
    """Test behavior for test_unknown_port_owner_blocks_native_start."""
    m, c = ctl
    calls = []
    monkeypatch.setattr(c, "prerequisites", lambda: None)
    monkeypatch.setattr(m, "pod_processes", list)
    monkeypatch.setattr(m, "active", lambda _: False)
    monkeypatch.setattr(m, "run", lambda a, **_kw: calls.append(a))
    monkeypatch.setattr(m.time, "sleep", lambda _: None)

    def occupied() -> None:
        msg = "occupied"
        raise OSError(msg)

    monkeypatch.setattr(m, "free_ports", occupied)
    with pytest.raises(OSError):
        c.activate("test")
    assert c.marker.exists()
    assert ["systemctl", "stop", m.AGENT] in calls
    assert ["systemctl", "start", m.NATIVE] not in calls


def test_image_determinism_and_binary_integrity(tmp_path, monkeypatch) -> None:
    """Test behavior for test_image_determinism_and_binary_integrity."""
    m = module("vpn-transit-image")
    binary = tmp_path / "binary"
    binary.write_bytes(b"fixture static binary")
    monkeypatch.setattr(m, "SHA", hashlib.sha256(binary.read_bytes()).hexdigest())
    a = tmp_path / "a.tar"
    b = tmp_path / "b.tar"
    assert m.build(binary, a) == m.build(binary, b)
    assert a.read_bytes() == b.read_bytes()
    with tarfile.open(a) as t:
        manifest = json.loads(t.extractfile("manifest.json").read())
        cfg = json.loads(t.extractfile(manifest[0]["Config"]).read())
        assert cfg["config"]["User"] == "65532:65532"
    binary.write_bytes(b"changed")
    with pytest.raises(AssertionError):
        m.build(binary, a)


def test_deployment_single_host_no_api_token_and_native_boot_fence() -> None:
    """Keep one host, no API token, and a boot fence that does not start the agent."""
    s = subprocess.check_output(
        ["helm", "template", "vpn-transit", str(ROOT / "charts/vpn-transit")], text=True
    )
    assert "type: Recreate" in s
    assert "hostNetwork: true" in s
    assert "automountServiceAccountToken: false" in s
    assert "imagePullPolicy: Never" in s
    assert "homelab.io/bootstrap" in s
    assert "NET_BIND_SERVICE" in s
    play = (ROOT / "ansible/playbooks/vpn-transit-mesh-runtime.yml").read_text()
    assert "ExecCondition=/usr/bin/test ! -e" in play
    assert "ExecCondition=+/usr/bin/test -e" in play
    assert "state: started" not in play  # prepare never steals live ports
    controller = (ROOT / "ansible/scripts/vpn-transit-failover.py").read_text()
    assert module("vpn-transit-failover").AGENT == "k3s-agent.service"
    assert "k3s.service" not in controller
    assert "flock" in controller
    assert "fsync" in controller
    assert "free_ports()" in controller


def test_tcp_time_wait_reuse_never_allows_a_live_owner_or_udp_reuse() -> None:
    """Test behavior for test_tcp_time_wait_reuse_never_allows_a_live_owner_or_udp_reuse."""
    module("vpn-transit-failover")
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as owner:
        owner.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        owner.bind(("0.0.0.0", 0))
        owner.listen()
        port = owner.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as challenger:
            challenger.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                challenger.bind(("0.0.0.0", port))
                challenger.listen(1)
    source = (ROOT / "ansible/scripts/vpn-transit-failover.py").read_text()
    assert (
        "iftyp==socket.SOCK_STREAM:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)"
        in "".join(source.split())
    )


def test_machine_https_exception_is_exact_not_a_human_acl_relaxation() -> None:
    """Keep the machine passthrough exact and the role default empty."""
    host = yaml.safe_load(
        (ROOT / "ansible/inventory/host_vars/socrat-2.yml").read_text()
    )
    defaults = yaml.safe_load(
        (ROOT / "ansible/roles/wireguard_private_web/defaults/main.yml").read_text()
    )
    assert host["wireguard_private_web_passthrough_sources"] == ["10.250.0.40"]
    assert defaults["wireguard_private_web_passthrough_sources"] == []
    assert host["public_dns_extra_listen"] == ["10.250.0.2@5354"]


def test_late_native_health_reconciles_without_replaying_lifecycle(
    ctl, monkeypatch
) -> None:
    """Test behavior for test_late_native_health_reconciles_without_replaying_lifecycle."""
    m, c = ctl
    m.atomic(c.marker, {"reason": "four failures"})
    c.save(mode="transition-to-native", failures=4, healthy=False)
    monkeypatch.setattr(m, "active", lambda unit: unit == m.NATIVE)
    monkeypatch.setattr(c, "healthy", lambda: True)
    calls = []
    monkeypatch.setattr(c, "prerequisites", lambda: calls.append("verified"))
    monkeypatch.setattr(m, "run", lambda *_a, **_kw: pytest.fail("no lifecycle replay"))
    c.tick()
    assert c.state["mode"] == "native"
    assert c.state["failures"] == 0
    assert c.state["healthy"]
    assert c.marker.exists()
    assert calls == ["verified"]
    receipts = list(m.ROOT.glob("*-native-reconciled.json"))
    assert len(receipts) == 1
    c.tick()
    assert len(list(m.ROOT.glob("*-native-reconciled.json"))) == 1


@pytest.mark.parametrize(
    ("native", "healthy"), [(False, True), (True, False), (False, False)]
)
def test_unhealthy_native_transition_stays_fenced(
    ctl, monkeypatch, native, healthy
) -> None:
    """Test behavior for test_unhealthy_native_transition_stays_fenced."""
    m, c = ctl
    m.atomic(c.marker, {})
    c.save(mode="transition-to-native", failures=4)
    monkeypatch.setattr(m, "active", lambda unit: native if unit == m.NATIVE else False)
    monkeypatch.setattr(c, "healthy", lambda: healthy)
    monkeypatch.setattr(
        c, "prerequisites", lambda: pytest.fail("no transition acceptance")
    )
    c.tick()
    assert c.state["mode"] == "transition-to-native"
    assert not c.state["healthy"]
    assert c.marker.exists()


def test_late_native_acceptance_refuses_active_agent(ctl, monkeypatch) -> None:
    """Test behavior for test_late_native_acceptance_refuses_active_agent."""
    m, c = ctl
    m.atomic(c.marker, {})
    c.save(mode="transition-to-native")
    monkeypatch.setattr(m, "active", lambda _unit: True)
    monkeypatch.setattr(c, "healthy", lambda: True)
    with pytest.raises(RuntimeError, match="Agent active"):
        c.tick()
    assert c.state["mode"] == "transition-to-native"
    assert c.marker.exists()


def test_late_native_acceptance_requires_prerequisites(ctl, monkeypatch) -> None:
    """Test behavior for test_late_native_acceptance_requires_prerequisites."""
    m, c = ctl
    m.atomic(c.marker, {})
    c.save(mode="transition-to-native")
    monkeypatch.setattr(m, "active", lambda unit: unit == m.NATIVE)
    monkeypatch.setattr(c, "healthy", lambda: True)

    def refuse() -> None:
        msg = "prerequisite drift"
        raise RuntimeError(msg)

    monkeypatch.setattr(c, "prerequisites", refuse)
    with pytest.raises(RuntimeError, match="prerequisite drift"):
        c.tick()
    assert c.state["mode"] == "transition-to-native"
    assert c.marker.exists()


def test_native_primary_requires_healthy_fenced_native_and_is_sticky(
    ctl, monkeypatch
) -> None:
    """Test behavior for test_native_primary_requires_healthy_fenced_native_and_is_sticky."""
    m, c = ctl
    monkeypatch.setattr(c, "prerequisites", lambda: None)
    monkeypatch.setattr(m, "active", lambda unit: unit == m.NATIVE)
    monkeypatch.setattr(c, "healthy", lambda: True)
    with pytest.raises(AssertionError):
        c.promote()
    m.atomic(c.marker, {"native": True})
    c.save(mode="native")
    c.promote()
    assert c.state["mode"] == "native-primary"
    assert c.marker.exists()
    c.tick()
    assert c.state["mode"] == "native-primary"
    with pytest.raises(AssertionError):
        c.failback()
    with pytest.raises(AssertionError):
        c.activate("accidental fallback replay")
    c.demote()
    assert c.state["mode"] == "native"
    assert c.marker.exists()


def test_unhealthy_primary_never_restarts_agent_or_releases_fence(
    ctl, monkeypatch
) -> None:
    """Test behavior for test_unhealthy_primary_never_restarts_agent_or_releases_fence."""
    m, c = ctl
    monkeypatch.setattr(c, "prerequisites", lambda: None)
    m.atomic(c.marker, {"native": True})
    c.save(mode="native-primary")
    monkeypatch.setattr(m, "active", lambda unit: unit == m.NATIVE)
    monkeypatch.setattr(c, "healthy", lambda: False)
    monkeypatch.setattr(
        m, "run", lambda *_a, **_k: pytest.fail("must not change lifecycle")
    )
    c.tick()
    assert not c.state["healthy"]
    assert c.marker.exists()
    with pytest.raises(AssertionError):
        c.demote()


@pytest.mark.parametrize(
    ("agent", "listeners", "upstream", "recover", "scope"),
    [
        (True, True, False, False, "upstream-or-path-unhealthy"),
        (True, True, True, True, "local-path-failed-upstream-healthy"),
        (True, False, False, False, "upstream-or-path-unhealthy"),
        (True, False, True, True, "local-listener-failed"),
        (False, True, False, False, "upstream-or-path-unhealthy"),
        (False, True, True, True, "local-agent-inactive"),
    ],
)
def test_failure_scope_uses_direct_upstream_not_api(
    ctl, monkeypatch, agent, listeners, upstream, recover, scope
) -> None:
    """Test behavior for test_failure_scope_uses_direct_upstream_not_api."""
    m, c = ctl
    monkeypatch.setattr(m, "active", lambda _unit: agent)
    monkeypatch.setattr(m, "local_listeners_respond", lambda: listeners)

    def check(_config, host, source, detail) -> bool:
        assert host == "10.250.0.2"
        assert source == ("10.250.0.40", 0)
        assert isinstance(detail, dict)  # probe records its observation in-place
        if not upstream:
            raise TimeoutError
        return True

    monkeypatch.setattr(m, "probe", check)
    d = c.recovery_scope()
    assert d["recover_local"] == recover
    assert d["scope"] == scope


def test_upstream_failure_never_fences_worker_or_releases_marker(
    ctl, monkeypatch
) -> None:
    """Test behavior for test_upstream_failure_never_fences_worker_or_releases_marker."""
    m, c = ctl
    monkeypatch.setattr(m, "boot_id", lambda: "boot")
    c.save(mode="kubernetes", boot_id="boot", grace_until=0)
    monkeypatch.setattr(c, "healthy", lambda: False)
    monkeypatch.setattr(
        c,
        "recovery_scope",
        lambda: {"recover_local": False, "scope": "upstream-or-path-unhealthy"},
    )
    monkeypatch.setattr(
        c,
        "activate",
        lambda _why: pytest.fail(
            "must not fence healthy local listeners for upstream failure"
        ),
    )
    for _ in range(12):
        c.tick()
    assert c.state["mode"] == "kubernetes"
    assert not c.state["healthy"]
    assert not c.marker.exists()
    assert c.state["failures"] == 4
    assert len(list(m.ROOT.glob("*-failure-classified.json"))) == 1
    # Upstream recovers but local TLS path remains bad: now a local recovery is justified.
    calls = []
    monkeypatch.setattr(c, "activate", calls.append)
    monkeypatch.setattr(
        c,
        "recovery_scope",
        lambda: {"recover_local": True, "scope": "local-path-failed-upstream-healthy"},
    )
    c.tick()
    assert len(calls) == 1


def test_probe_failure_records_stage_not_private_path(ctl, monkeypatch) -> None:
    """Test behavior for test_probe_failure_records_stage_not_private_path."""
    m, c = ctl

    def fail(*_a, **_kw) -> None:
        raise TimeoutError

    monkeypatch.setattr(m.socket, "create_connection", fail)
    assert not c.healthy()
    assert c.last_probe["stage"] == "tcp"
    assert c.last_probe["port"] == 32053
    assert c.last_probe["error"] == "TimeoutError"
    assert "/test" not in json.dumps(c.last_probe)


def test_boot_grace_never_refreshes_old_green_health_or_carries_failure_count(
    ctl, monkeypatch
) -> None:
    """Test boot grace resets stale health."""
    m, c = ctl
    c.save(mode="kubernetes", healthy=True, failures=3, boot_id="old")
    monkeypatch.setattr(m, "boot_id", lambda: "new")
    monkeypatch.setattr(c, "healthy", lambda: False)
    monkeypatch.setattr(c, "activate", lambda _: pytest.fail("boot grace"))
    c.tick()
    assert c.state["healthy"] is False
    assert c.state["failures"] == 0
    c.tick()
    assert c.state["healthy"] is False
    assert c.state["failures"] == 0


def test_failed_websocket_diagnostic_does_not_store_private_path(
    ctl, monkeypatch
) -> None:
    """Test failed websocket diagnostics avoid private paths."""
    m, c = ctl

    class Connection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args) -> None:
            pass

        def sendall(self, data) -> None:
            assert b"/test" in data

        def recv(self, n) -> bytes:
            return b"HTTP/1.1 403 Forbidden\r\n"

    class Context:
        def wrap_socket(self, s, server_hostname) -> Connection:
            assert server_hostname == "vpn.alchemmist.xyz"
            return Connection()

    monkeypatch.setattr(m.socket, "create_connection", lambda *_a, **_kw: Connection())
    monkeypatch.setattr(m.ssl, "create_default_context", Context)
    assert not c.healthy()
    assert c.last_probe["http_status"] == 403
    assert c.last_probe["stage"] == "websocket"
    assert "/test" not in json.dumps(c.last_probe)


def test_native_cooldown_and_retry_backoff(ctl, monkeypatch):
    m, c = ctl
    c.config["warm_return_enabled"] = True
    c.save(mode="native")
    m.atomic(c.marker, {})
    monkeypatch.setattr(m, "active", lambda unit: unit == m.NATIVE)
    monkeypatch.setattr(c, "healthy", lambda: True)
    monkeypatch.setattr(m, "boot_id", lambda: "boot")
    calls = []
    monkeypatch.setattr(c, "warm_return", lambda: calls.append(1))
    for now in (15, 1814, 1815, 1816):
        monkeypatch.setattr(m.time, "monotonic", lambda: now)
        c.tick()
    assert calls == [1]
    assert c.state["return_after"] == 3615


def test_interrupted_warm_return_recovers_before_monitoring(ctl, monkeypatch):
    m, c = ctl
    c.config["warm_return_enabled"] = True
    c.save(mode="warming")
    m.atomic(c.marker, {})
    calls = []
    monkeypatch.setattr(c, "activate", calls.append)
    c.tick()
    assert calls == ["recover interrupted warm return"]


def test_agent_exception_requires_live_same_boot_warming(ctl, monkeypatch, tmp_path):
    m, c = ctl
    monkeypatch.setattr(type(c), "permit", property(lambda _: tmp_path / "permit"))
    monkeypatch.setattr(m, "boot_id", lambda: "this-boot")
    monkeypatch.setattr(m, "active", lambda unit: unit == m.NATIVE)
    c.config["warm_return_enabled"] = True
    m.atomic(c.marker, {})
    c.save(mode="native")
    assert not c.agent_allowed()
    c.save(mode="warming", warming_boot="old")
    assert not c.agent_allowed()
    c.save(warming_boot="this-boot")
    assert c.agent_allowed()
    c.permit.touch()
    assert not c.agent_allowed()


def test_manual_return_cannot_bypass_busy_shared_lock(ctl, monkeypatch):
    m, c = ctl
    c.config["warm_return_enabled"] = True
    m.atomic(c.marker, {})
    c.save(mode="native")
    monkeypatch.setattr(c, "prerequisites", lambda: None)
    monkeypatch.setattr(c, "warm_return", lambda: None)
    monkeypatch.setattr(
        m, "run", lambda *_a, **_k: pytest.fail("must not touch native relay")
    )
    with pytest.raises(RuntimeError, match="deferred"):
        c.failback()
    assert c.marker.exists()
