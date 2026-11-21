"""Tests for the vpn_failover role's embedded failover script."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "ansible/roles/vpn_failover/files/vpn_failover.py"

# Named mirrors of the watchdog defaults asserted below.
WEBSOCKET_FORBIDDEN_STATUS = 403
KUBERNETES_START_TIMEOUT_SECONDS = 180
UNIT_COMMAND_TIMEOUT_SECONDS = 40
CONFIGURED_K3S_START_TIMEOUT_SECONDS = 240
EXPECTED_UNHEALTHY_HEALTH_CALLS = 7
STATE_FILE_MODE = 0o600
SPEC = importlib.util.spec_from_file_location("vpn_failover", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeWatchdog(MODULE.Watchdog):
    def __init__(self, directory):
        super().__init__(
            {
                "state_dir": directory,
                "listen_ports": [],
                "failure_threshold": 4,
                "confirmation_interval_seconds": 0,
                "native_start_grace_seconds": 0,
            }
        )
        self.good = False
        self.uptime = 300
        self.events = []
        self.running = set()
        self.stuck = False
        self.ports = []
        self.invalid = False

    def service_installed(self, unit):
        return unit == self.agent

    def clock(self):
        return "boot-one", self.uptime

    def health(self):
        return {"healthy": self.good, "errors": [] if self.good else ["unavailable"]}

    def preflight(self):
        if self.invalid:
            raise RuntimeError("Missing assets")

    def fence(self):
        self.events.append("fence")
        if self.stuck:
            raise RuntimeError("Cannot fence")

    def guard(self):
        if not (self.state / "active").exists() or self.stuck:
            raise RuntimeError("Unsafe start")

    def occupied(self):
        return self.ports

    def service_active(self, unit):
        return unit in self.running

    def command(self, *args):
        self.events.append(args)
        if args[1] == "start":
            self.running.add(args[2])
        elif args[1] == "stop":
            self.running.discard(args[2])
        return ""


class FailoverTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.watchdog = FakeWatchdog(self.directory.name)

    def test_boot_grace_avoids_failure_counting(self):
        self.watchdog.uptime = 20
        assert self.watchdog.tick() == {"mode": "grace"}
        assert not (self.watchdog.state / "failures.json").exists()

    def test_four_failures_required_and_latch_persisted(self):
        for count in range(1, 4):
            assert self.watchdog.tick()["failures"] == count
            assert not self.watchdog.running
        assert self.watchdog.tick()["mode"] == "fallback"
        assert (self.watchdog.state / "active").exists()
        assert self.watchdog.events[0] == "fence"
        assert self.watchdog.running == set(MODULE.NATIVE_UNITS)

    def test_recovery_resets_consecutive_errors(self):
        self.watchdog.tick()
        self.watchdog.good = True
        assert self.watchdog.tick()["failures"] == 0
        self.watchdog.good = False
        assert self.watchdog.tick()["failures"] == 1

    def test_failed_fencing_preserves_latch_without_native_start(self):
        self.watchdog.stuck = True
        with self.assertRaises(RuntimeError):
            self.watchdog.activate()
        assert (self.watchdog.state / "active").exists()
        assert not self.watchdog.running
        self.watchdog.stuck = False
        self.watchdog.tick()
        assert self.watchdog.running == set(MODULE.NATIVE_UNITS)

    def test_missing_assets_do_not_fence_working_kubernetes(self):
        self.watchdog.invalid = True
        with self.assertRaises(RuntimeError):
            self.watchdog.activate()
        assert not (self.watchdog.state / "active").exists()
        assert self.watchdog.events == []

    def test_occupied_ports_prevent_first_native_start(self):
        self.watchdog.ports = [("tcp", 443)]
        with self.assertRaises(RuntimeError):
            self.watchdog.activate()
        assert not self.watchdog.running
        assert (self.watchdog.state / "active").exists()

    def test_healthy_fallback_does_not_automatically_fail_back(self):
        self.watchdog.activate()
        self.watchdog.good = True
        self.watchdog.tick()
        assert (self.watchdog.state / "active").exists()
        assert self.watchdog.agent not in self.watchdog.running

    def test_maintenance_inhibit_prevents_actions(self):
        (self.watchdog.state / "inhibit").touch()
        assert self.watchdog.tick() == {"mode": "inhibited"}
        assert self.watchdog.events == []

    def test_failback_keeps_fence_when_native_ports_remain(self):
        self.watchdog.activate()
        self.watchdog.ports = [("tcp", 443)]
        with self.assertRaises(RuntimeError):
            self.watchdog.failback()
        assert (self.watchdog.state / "active").exists()
        assert self.watchdog.agent not in self.watchdog.running

    def test_failback_releases_latch_after_stopping_native_and_adds_grace(self):
        self.watchdog.activate()
        self.watchdog.failback()
        assert not (self.watchdog.state / "active").exists()
        assert self.watchdog.running == {self.watchdog.agent}
        assert self.watchdog.tick() == {"mode": "grace"}

    def test_new_boot_resets_old_failures(self):
        self.watchdog.write(
            "failures.json", {"boot_id": "old", "failures": 100, "grace_until": 999999}
        )
        assert self.watchdog.tick()["failures"] == 1

    def test_partial_activation_does_not_restart_running_units(self):
        self.watchdog.activate()
        self.watchdog.running.remove(MODULE.NATIVE_UNITS[-1])
        self.watchdog.events.clear()
        self.watchdog.tick()
        assert self.watchdog.events == ["fence", ("systemctl", "start", MODULE.NATIVE_UNITS[-1])]

    def test_partial_activation_refuses_inactive_unit_port_conflict(self):
        self.watchdog.activate()
        unit = MODULE.NATIVE_UNITS[-1]
        self.watchdog.running.remove(unit)
        self.watchdog.config["native_unit_ports"] = {unit: [{"protocol": "tcp", "port": 443}]}
        self.watchdog.ports = [("tcp", 443)]
        with self.assertRaises(RuntimeError):
            self.watchdog.tick()
        assert unit not in self.watchdog.running

    def test_unhealthy_active_native_services_restart_after_threshold(self):
        self.watchdog.activate()
        self.watchdog.events.clear()
        self.watchdog.tick()
        self.watchdog.tick()
        assert not any(
            isinstance(event, tuple) and event[1] == "stop" for event in self.watchdog.events
        )
        assert self.watchdog.tick()["restarted"]
        assert self.watchdog.running == set(MODULE.NATIVE_UNITS)
        assert (self.watchdog.state / "active").exists()

    def test_native_recovery_health_resets_restart_counter(self):
        self.watchdog.activate()
        self.watchdog.tick()
        self.watchdog.good = True
        assert self.watchdog.tick()["failures"] == 0
        self.watchdog.good = False
        assert self.watchdog.tick()["failures"] == 1

    def test_pidfd_signal_targets_verified_kubernetes_process(self):
        with (
            mock.patch.object(MODULE.os, "pidfd_open", return_value=91, create=True),
            mock.patch.object(MODULE.signal, "pidfd_send_signal", create=True) as send,
            mock.patch.object(MODULE.os, "close") as close,
            mock.patch.object(MODULE.Path, "read_text", return_value="0::/kubepods/pod-one"),
        ):
            self.watchdog.terminate(123, MODULE.signal.SIGTERM)
        send.assert_called_once_with(91, MODULE.signal.SIGTERM)
        close.assert_called_once_with(91)

    def test_changed_process_cgroup_refuses_signal(self):
        with (
            mock.patch.object(MODULE.os, "pidfd_open", return_value=91, create=True),
            mock.patch.object(MODULE.signal, "pidfd_send_signal", create=True) as send,
            mock.patch.object(MODULE.os, "close"),
            mock.patch.object(
                MODULE.Path, "read_text", return_value="0::/system.slice/ssh.service"
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.watchdog.terminate(123, MODULE.signal.SIGTERM)
        send.assert_not_called()


class KubernetesFencingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.watchdog = MODULE.Watchdog(
            {"state_dir": self.directory.name, "agent_unit": "k3s.service"}
        )
        self.loads = {"k3s-agent.service": "loaded", "k3s.service": "loaded"}
        self.active = {"k3s-agent.service", "k3s.service"}
        self.commands = []
        self.watchdog.command = self.command

    def command(self, *args):
        self.commands.append(args)
        if args[1] == "show":
            if args[3] == "--property=LoadState":
                return self.loads[args[2]]
            return "active" if args[2] in self.active else "inactive"
        if args[1] == "stop":
            self.active.discard(args[2])

    def test_fence_stops_both_installed_units(self):
        with mock.patch.object(self.watchdog, "processes", return_value=[]):
            self.watchdog.fence()
        assert not self.active
        assert ("systemctl", "stop", "k3s-agent.service") in self.commands
        assert ("systemctl", "stop", "k3s.service") in self.commands

    def test_missing_agent_is_ignored_but_server_is_stopped(self):
        self.loads["k3s-agent.service"] = "not-found"
        self.active = {"k3s.service"}
        with mock.patch.object(self.watchdog, "processes", return_value=[]):
            self.watchdog.fence()
        assert ("systemctl", "stop", "k3s-agent.service") not in self.commands
        assert not self.active

    def test_active_server_blocks_native_even_when_agent_is_absent(self):
        (self.watchdog.state / "active").touch()
        self.loads["k3s-agent.service"] = "not-found"
        self.active = {"k3s.service"}
        with mock.patch.object(self.watchdog, "processes", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "verified Kubernetes fencing"):
                self.watchdog.guard()

    def test_unknown_load_state_fails_closed(self):
        self.loads["k3s.service"] = "error"
        with self.assertRaisesRegex(RuntimeError, "Cannot verify systemd unit"):
            self.watchdog.fence()
        assert not any(args[1] == "stop" for args in self.commands)

    def test_fence_refuses_service_still_active(self):
        with (
            mock.patch.object(self.watchdog, "service_active", return_value=True),
            mock.patch.object(self.watchdog, "processes") as processes,
        ):
            with self.assertRaisesRegex(RuntimeError, "did not stop"):
                self.watchdog.fence()
        processes.assert_not_called()

    def test_server_and_agent_cgroups_are_both_fenced(self):
        for unit in self.watchdog.fenced_units:
            with (
                self.subTest(unit=unit),
                mock.patch.object(MODULE.os, "pidfd_open", return_value=91, create=True),
                mock.patch.object(MODULE.signal, "pidfd_send_signal", create=True) as send,
                mock.patch.object(MODULE.os, "close"),
                mock.patch.object(
                    MODULE.Path, "read_text", return_value="0::/system.slice/" + unit
                ),
            ):
                self.watchdog.terminate(123, MODULE.signal.SIGTERM)
                send.assert_called_once_with(91, MODULE.signal.SIGTERM)

    def test_failback_starts_only_configured_server(self):
        (self.watchdog.state / "active").touch()
        with (
            mock.patch.object(self.watchdog, "processes", return_value=[]),
            mock.patch.object(self.watchdog, "occupied", return_value=[]),
            mock.patch.object(self.watchdog, "clock", return_value=("boot", 300)),
        ):
            self.watchdog.failback()
        assert [args for args in self.commands if args[1] == "start"] == [
            ("systemctl", "start", "k3s.service")
        ]
        assert not (self.watchdog.state / "active").exists()


class ProbeDiagnosticsTests(unittest.TestCase):
    def watchdog(self):
        return MODULE.Watchdog(
            {
                "tcp_endpoints": [],
                "websocket": {"host": "example.invalid", "path": "/private-route"},
            }
        )

    def test_connect_failure_is_classified_without_exception_text(self):
        with mock.patch.object(
            MODULE.socket,
            "create_connection",
            side_effect=TimeoutError("sensitive diagnostic text"),
        ):
            result = self.watchdog().health()
        assert not result["healthy"]
        assert result["websocket_diagnostics"]["stage"] == "tcp_connect"
        assert result["websocket_diagnostics"]["exception"] == "TimeoutError"
        assert "sensitive" not in json.dumps(result)
        assert "private-route" not in json.dumps(result)

    def test_rejected_upgrade_records_only_numeric_status(self):
        context = mock.MagicMock()
        stream = context.wrap_socket.return_value.__enter__.return_value
        stream.recv.return_value = b"HTTP/1.1 403 Forbidden\r\n\r\nprivate data"
        with (
            mock.patch.object(MODULE.ssl, "create_default_context", return_value=context),
            mock.patch.object(MODULE.socket, "create_connection"),
        ):
            result = self.watchdog().health()
        assert result["websocket_diagnostics"]["http_status"] == WEBSOCKET_FORBIDDEN_STATUS
        assert result["websocket_diagnostics"]["stage"] == "websocket_response"
        assert "private data" not in json.dumps(result)


class CommandDeadlineTests(unittest.TestCase):
    def test_rejoining_kubernetes_has_separate_deadline(self):
        w = MODULE.Watchdog({})
        with mock.patch.object(MODULE.subprocess, "run") as run:
            run.return_value.stdout = ""
            w.command("systemctl", "start", "k3s.service")
            assert run.call_args.kwargs["timeout"] == KUBERNETES_START_TIMEOUT_SECONDS
            w.command("systemctl", "stop", "k3s.service")
            assert run.call_args.kwargs["timeout"] == UNIT_COMMAND_TIMEOUT_SECONDS
            w.command("systemctl", "start", "homelab-vpn-primary.service")
            assert run.call_args.kwargs["timeout"] == UNIT_COMMAND_TIMEOUT_SECONDS

    def test_kubernetes_deadline_can_be_configured(self):
        w = MODULE.Watchdog({"kubernetes_start_timeout_seconds": 240})
        with mock.patch.object(MODULE.subprocess, "run") as run:
            run.return_value.stdout = ""
            w.command("systemctl", "start", "k3s-agent.service")
            assert run.call_args.kwargs["timeout"] == CONFIGURED_K3S_START_TIMEOUT_SECONDS


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.w = FakeWatchdog(self.directory.name)

    def test_recovery_during_confirmation_cancels_fencing(self):
        self.w.health = mock.Mock(
            side_effect=[{"healthy": False, "errors": ["unavailable"]}] * 4
            + [{"healthy": True, "errors": []}]
        )
        for _ in range(3):
            self.w.tick()
        result = self.w.tick()
        assert result["activation_cancelled"]
        assert result["failures"] == 0
        assert self.w.events == []
        assert not (self.w.state / "active").exists()

    def test_all_confirmation_samples_must_remain_unhealthy(self):
        self.w.health = mock.Mock(return_value={"healthy": False, "errors": ["unavailable"]})
        for _ in range(4):
            result = self.w.tick()
        assert result["mode"] == "fallback"
        assert (
            self.w.health.call_count == EXPECTED_UNHEALTHY_HEALTH_CALLS
        )  # four + two confirms + native
        assert self.w.events[0] == "fence"

    def test_native_warmup_does_not_count_startup_failures(self):
        self.w.config["native_start_grace_seconds"] = 30
        assert self.w.activate()["warming_up"]
        for _ in range(5):
            assert self.w.tick()["warming_up"]
        assert not any(isinstance(e, tuple) and e[1] == "stop" for e in self.w.events)
        self.w.uptime += 31
        assert self.w.tick()["failures"] == 1

    def test_native_restart_cancelled_if_confirmation_recovers(self):
        self.w.activate()
        self.w.tick()
        self.w.tick()
        self.w.health = mock.Mock(
            side_effect=[
                {"healthy": False, "errors": ["unavailable"]},
                {"healthy": True, "errors": []},
            ]
        )
        assert self.w.tick()["restart_cancelled"]
        assert not any(isinstance(e, tuple) and e[1] == "stop" for e in self.w.events)

    def test_stale_agent_target_keeps_native_untouched(self):
        self.w.activate()
        self.w.events.clear()
        self.w.agent = "k3s-agent.service"
        self.w.service_installed = lambda unit: True
        with self.assertRaisesRegex(RuntimeError, "Legacy agent"):
            self.w.failback()
        assert self.w.events == []
        assert (self.w.state / "active").exists()

    def test_missing_target_keeps_native_untouched(self):
        self.w.activate()
        self.w.events.clear()
        self.w.service_installed = lambda unit: False
        with self.assertRaisesRegex(RuntimeError, "not installed"):
            self.w.failback()
        assert self.w.events == []

    def test_failed_kubernetes_start_restores_native_immediately(self):
        self.w.activate()
        command = self.w.command

        def failed(*args):
            if args == ("systemctl", "start", self.w.agent):
                raise RuntimeError("start failed")
            return command(*args)

        self.w.command = failed
        with self.assertRaisesRegex(RuntimeError, "start failed"):
            self.w.failback()
        assert self.w.running == set(MODULE.NATIVE_UNITS)
        assert (self.w.state / "active").exists()

    def test_failure_receipt_is_durable(self):
        self.w.tick()
        receipt = json.loads((self.w.state / "last_failure.json").read_text())
        assert receipt["mode"] == "kubernetes"
        assert not receipt["healthy"]
        assert (self.w.state / "last_failure.json").stat().st_mode & 0o777 == STATE_FILE_MODE


class ServiceIdentityContractTests(unittest.TestCase):
    def test_python_and_ansible_defaults_use_current_server(self):
        assert MODULE.Watchdog({}).agent == "k3s.service"
        import yaml

        root = SOURCE.parents[4]
        defaults = yaml.safe_load(
            (root / "ansible/roles/vpn_failover/defaults/main.yml").read_text()
        )
        assert defaults["vpn_failover_k3s_unit"] == "k3s.service"
        assert set(defaults["vpn_failover_fenced_units"]) == {"k3s.service", "k3s-agent.service"}


if __name__ == "__main__":
    unittest.main()
