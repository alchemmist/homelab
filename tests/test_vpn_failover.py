import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from typing import Protocol
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "ansible/roles/vpn_failover/files/vpn_failover.py"
SPEC = importlib.util.spec_from_file_location("vpn_failover", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _mapping(value: object) -> dict[str, object]:
    """Narrow decoded report fields to mappings for typed test callers."""
    assert isinstance(value, dict)
    return value


class FakeWatchdog(MODULE.Watchdog):
    def __init__(self, directory: str) -> None:
        super().__init__(
            {
                "state_dir": directory,
                "listen_ports": [],
                "failure_threshold": 4,
                "confirmation_interval_seconds": 0,
                "native_start_grace_seconds": 0,
            }
        )
        self.good: bool = False
        self.uptime: int = 300
        self.events: list[object] = []
        self.running: set[str] = set()
        self.stuck: bool = False
        self.ports: list[tuple[str, int]] = []
        self.invalid: bool = False

    def service_installed(self, unit: str) -> bool:
        installed: bool = unit == self.agent
        return installed

    def clock(self) -> tuple[str, int]:
        return "boot-one", self.uptime

    def health(self) -> dict[str, object]:
        return {"healthy": self.good, "errors": [] if self.good else ["unavailable"]}

    def preflight(self) -> None:
        if self.invalid:
            raise RuntimeError("Missing assets")

    def fence(self) -> None:
        self.events.append("fence")
        if self.stuck:
            raise RuntimeError("Cannot fence")

    def guard(self) -> None:
        if not (self.state / "active").exists() or self.stuck:
            raise RuntimeError("Unsafe start")

    def occupied(self) -> list[tuple[str, int]]:
        return self.ports

    def service_active(self, unit: str) -> bool:
        return unit in self.running

    def command(self, *args: str) -> str:
        self.events.append(args)
        if args[1] == "start":
            self.running.add(args[2])
        elif args[1] == "stop":
            self.running.discard(args[2])
        return ""


class FailoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.watchdog = FakeWatchdog(self.directory.name)

    def test_boot_grace_avoids_failure_counting(self) -> None:
        self.watchdog.uptime = 20
        self.assertEqual(self.watchdog.tick(), {"mode": "grace"})
        self.assertFalse((self.watchdog.state / "failures.json").exists())

    def test_four_failures_required_and_latch_persisted(self) -> None:
        for count in range(1, 4):
            self.assertEqual(self.watchdog.tick()["failures"], count)
            self.assertFalse(self.watchdog.running)
        self.assertEqual(self.watchdog.tick()["mode"], "fallback")
        self.assertTrue((self.watchdog.state / "active").exists())
        self.assertEqual(self.watchdog.events[0], "fence")
        self.assertEqual(self.watchdog.running, set(MODULE.NATIVE_UNITS))

    def test_recovery_resets_consecutive_errors(self) -> None:
        self.watchdog.tick()
        self.watchdog.good = True
        self.assertEqual(self.watchdog.tick()["failures"], 0)
        self.watchdog.good = False
        self.assertEqual(self.watchdog.tick()["failures"], 1)

    def test_failed_fencing_preserves_latch_without_native_start(self) -> None:
        self.watchdog.stuck = True
        with self.assertRaises(RuntimeError):
            self.watchdog.activate()
        self.assertTrue((self.watchdog.state / "active").exists())
        self.assertFalse(self.watchdog.running)
        self.watchdog.stuck = False
        self.watchdog.tick()
        self.assertEqual(self.watchdog.running, set(MODULE.NATIVE_UNITS))

    def test_missing_assets_do_not_fence_working_kubernetes(self) -> None:
        self.watchdog.invalid = True
        with self.assertRaises(RuntimeError):
            self.watchdog.activate()
        self.assertFalse((self.watchdog.state / "active").exists())
        self.assertEqual(self.watchdog.events, [])

    def test_occupied_ports_prevent_first_native_start(self) -> None:
        self.watchdog.ports = [("tcp", 443)]
        with self.assertRaises(RuntimeError):
            self.watchdog.activate()
        self.assertFalse(self.watchdog.running)
        self.assertTrue((self.watchdog.state / "active").exists())

    def test_healthy_fallback_does_not_automatically_fail_back(self) -> None:
        self.watchdog.activate()
        self.watchdog.good = True
        self.watchdog.tick()
        self.assertTrue((self.watchdog.state / "active").exists())
        self.assertNotIn(self.watchdog.agent, self.watchdog.running)

    def test_maintenance_inhibit_prevents_actions(self) -> None:
        (self.watchdog.state / "inhibit").touch()
        self.assertEqual(self.watchdog.tick(), {"mode": "inhibited"})
        self.assertEqual(self.watchdog.events, [])

    def test_failback_keeps_fence_when_native_ports_remain(self) -> None:
        self.watchdog.activate()
        self.watchdog.ports = [("tcp", 443)]
        with self.assertRaises(RuntimeError):
            self.watchdog.failback()
        self.assertTrue((self.watchdog.state / "active").exists())
        self.assertNotIn(self.watchdog.agent, self.watchdog.running)

    def test_failback_releases_latch_after_stopping_native_and_adds_grace(self) -> None:
        self.watchdog.activate()
        self.watchdog.failback()
        self.assertFalse((self.watchdog.state / "active").exists())
        self.assertEqual(self.watchdog.running, {self.watchdog.agent})
        self.assertEqual(self.watchdog.tick(), {"mode": "grace"})

    def test_new_boot_resets_old_failures(self) -> None:
        self.watchdog.write(
            "failures.json", {"boot_id": "old", "failures": 100, "grace_until": 999999}
        )
        self.assertEqual(self.watchdog.tick()["failures"], 1)

    def test_partial_activation_does_not_restart_running_units(self) -> None:
        self.watchdog.activate()
        self.watchdog.running.remove(MODULE.NATIVE_UNITS[-1])
        self.watchdog.events.clear()
        self.watchdog.tick()
        self.assertEqual(
            self.watchdog.events, ["fence", ("systemctl", "start", MODULE.NATIVE_UNITS[-1])]
        )

    def test_partial_activation_refuses_inactive_unit_port_conflict(self) -> None:
        self.watchdog.activate()
        unit = MODULE.NATIVE_UNITS[-1]
        self.watchdog.running.remove(unit)
        self.watchdog.config["native_unit_ports"] = {unit: [{"protocol": "tcp", "port": 443}]}
        self.watchdog.ports = [("tcp", 443)]
        with self.assertRaises(RuntimeError):
            self.watchdog.tick()
        self.assertNotIn(unit, self.watchdog.running)

    def test_unhealthy_active_native_services_restart_after_threshold(self) -> None:
        self.watchdog.activate()
        self.watchdog.events.clear()
        self.watchdog.tick()
        self.watchdog.tick()
        self.assertFalse(
            any(isinstance(event, tuple) and event[1] == "stop" for event in self.watchdog.events)
        )
        self.assertTrue(self.watchdog.tick()["restarted"])
        self.assertEqual(self.watchdog.running, set(MODULE.NATIVE_UNITS))
        self.assertTrue((self.watchdog.state / "active").exists())

    def test_native_recovery_health_resets_restart_counter(self) -> None:
        self.watchdog.activate()
        self.watchdog.tick()
        self.watchdog.good = True
        self.assertEqual(self.watchdog.tick()["failures"], 0)
        self.watchdog.good = False
        self.assertEqual(self.watchdog.tick()["failures"], 1)

    def test_pidfd_signal_targets_verified_kubernetes_process(self) -> None:
        with (
            mock.patch.object(MODULE.os, "pidfd_open", return_value=91, create=True),
            mock.patch.object(MODULE.signal, "pidfd_send_signal", create=True) as send,
            mock.patch.object(MODULE.os, "close") as close,
            mock.patch.object(MODULE.Path, "read_text", return_value="0::/kubepods/pod-one"),
        ):
            self.watchdog.terminate(123, MODULE.signal.SIGTERM)
        send.assert_called_once_with(91, MODULE.signal.SIGTERM)
        close.assert_called_once_with(91)

    def test_changed_process_cgroup_refuses_signal(self) -> None:
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
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.watchdog = MODULE.Watchdog(
            {"state_dir": self.directory.name, "agent_unit": "k3s.service"}
        )
        self.loads = {"k3s-agent.service": "loaded", "k3s.service": "loaded"}
        self.active = {"k3s-agent.service", "k3s.service"}
        self.commands: list[tuple[str, ...]] = []
        self.watchdog.command = self.command

    def command(self, *args: str) -> str | None:
        self.commands.append(args)
        if args[1] == "show":
            if args[3] == "--property=LoadState":
                return self.loads[args[2]]
            return "active" if args[2] in self.active else "inactive"
        if args[1] == "stop":
            self.active.discard(args[2])
            return None
        return None

    def test_fence_stops_both_installed_units(self) -> None:
        with mock.patch.object(self.watchdog, "processes", return_value=[]):
            self.watchdog.fence()
        self.assertFalse(self.active)
        self.assertIn(("systemctl", "stop", "k3s-agent.service"), self.commands)
        self.assertIn(("systemctl", "stop", "k3s.service"), self.commands)

    def test_missing_agent_is_ignored_but_server_is_stopped(self) -> None:
        self.loads["k3s-agent.service"] = "not-found"
        self.active = {"k3s.service"}
        with mock.patch.object(self.watchdog, "processes", return_value=[]):
            self.watchdog.fence()
        self.assertNotIn(("systemctl", "stop", "k3s-agent.service"), self.commands)
        self.assertFalse(self.active)

    def test_active_server_blocks_native_even_when_agent_is_absent(self) -> None:
        (self.watchdog.state / "active").touch()
        self.loads["k3s-agent.service"] = "not-found"
        self.active = {"k3s.service"}
        with mock.patch.object(self.watchdog, "processes", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "verified Kubernetes fencing"):
                self.watchdog.guard()

    def test_unknown_load_state_fails_closed(self) -> None:
        self.loads["k3s.service"] = "error"
        with self.assertRaisesRegex(RuntimeError, "Cannot verify systemd unit"):
            self.watchdog.fence()
        self.assertFalse(any(args[1] == "stop" for args in self.commands))

    def test_fence_refuses_service_still_active(self) -> None:
        with (
            mock.patch.object(self.watchdog, "service_active", return_value=True),
            mock.patch.object(self.watchdog, "processes") as processes,
        ):
            with self.assertRaisesRegex(RuntimeError, "did not stop"):
                self.watchdog.fence()
        processes.assert_not_called()

    def test_server_and_agent_cgroups_are_both_fenced(self) -> None:
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

    def test_failback_starts_only_configured_server(self) -> None:
        (self.watchdog.state / "active").touch()
        with (
            mock.patch.object(self.watchdog, "processes", return_value=[]),
            mock.patch.object(self.watchdog, "occupied", return_value=[]),
            mock.patch.object(self.watchdog, "clock", return_value=("boot", 300)),
        ):
            self.watchdog.failback()
        self.assertEqual(
            [args for args in self.commands if args[1] == "start"],
            [("systemctl", "start", "k3s.service")],
        )
        self.assertFalse((self.watchdog.state / "active").exists())


class WatchdogProbe(Protocol):
    """Static surface of the dynamically loaded failover watchdog used by probes."""

    def health(self) -> dict[str, object]: ...


class ProbeDiagnosticsTests(unittest.TestCase):
    def watchdog(self) -> WatchdogProbe:
        probe: WatchdogProbe = MODULE.Watchdog(
            {
                "tcp_endpoints": [],
                "websocket": {"host": "example.invalid", "path": "/private-route"},
            }
        )
        return probe

    def test_connect_failure_is_classified_without_exception_text(self) -> None:
        with mock.patch.object(
            MODULE.socket,
            "create_connection",
            side_effect=TimeoutError("sensitive diagnostic text"),
        ):
            result = self.watchdog().health()
        self.assertFalse(result["healthy"])
        diagnostics = _mapping(result["websocket_diagnostics"])
        self.assertEqual(diagnostics["stage"], "tcp_connect")
        self.assertEqual(diagnostics["exception"], "TimeoutError")
        self.assertNotIn("sensitive", json.dumps(result))
        self.assertNotIn("private-route", json.dumps(result))

    def test_rejected_upgrade_records_only_numeric_status(self) -> None:
        context = mock.MagicMock()
        stream = context.wrap_socket.return_value.__enter__.return_value
        stream.recv.return_value = b"HTTP/1.1 403 Forbidden\r\n\r\nprivate data"
        with (
            mock.patch.object(MODULE.ssl, "create_default_context", return_value=context),
            mock.patch.object(MODULE.socket, "create_connection"),
        ):
            result = self.watchdog().health()
        diagnostics = _mapping(result["websocket_diagnostics"])
        self.assertEqual(diagnostics["http_status"], 403)
        self.assertEqual(diagnostics["stage"], "websocket_response")
        self.assertNotIn("private data", json.dumps(result))


class CommandDeadlineTests(unittest.TestCase):
    def test_rejoining_kubernetes_has_separate_deadline(self) -> None:
        w = MODULE.Watchdog({})
        with mock.patch.object(MODULE.subprocess, "run") as run:
            run.return_value.stdout = ""
            w.command("systemctl", "start", "k3s.service")
            self.assertEqual(run.call_args.kwargs["timeout"], 180)
            w.command("systemctl", "stop", "k3s.service")
            self.assertEqual(run.call_args.kwargs["timeout"], 40)
            w.command("systemctl", "start", "homelab-vpn-primary.service")
            self.assertEqual(run.call_args.kwargs["timeout"], 40)

    def test_kubernetes_deadline_can_be_configured(self) -> None:
        w = MODULE.Watchdog({"kubernetes_start_timeout_seconds": 240})
        with mock.patch.object(MODULE.subprocess, "run") as run:
            run.return_value.stdout = ""
            w.command("systemctl", "start", "k3s-agent.service")
            self.assertEqual(run.call_args.kwargs["timeout"], 240)


class HardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.w = FakeWatchdog(self.directory.name)

    def test_recovery_during_confirmation_cancels_fencing(self) -> None:
        self.w.health = mock.Mock(
            side_effect=[{"healthy": False, "errors": ["unavailable"]}] * 4
            + [{"healthy": True, "errors": []}]
        )
        for _ in range(3):
            self.w.tick()
        result = self.w.tick()
        self.assertTrue(result["activation_cancelled"])
        self.assertEqual(result["failures"], 0)
        self.assertEqual(self.w.events, [])
        self.assertFalse((self.w.state / "active").exists())

    def test_all_confirmation_samples_must_remain_unhealthy(self) -> None:
        self.w.health = mock.Mock(return_value={"healthy": False, "errors": ["unavailable"]})
        for _ in range(4):
            result = self.w.tick()
        self.assertEqual(result["mode"], "fallback")
        self.assertEqual(self.w.health.call_count, 7)  # four + two confirms + native
        self.assertEqual(self.w.events[0], "fence")

    def test_native_warmup_does_not_count_startup_failures(self) -> None:
        self.w.config["native_start_grace_seconds"] = 30
        self.assertTrue(self.w.activate()["warming_up"])
        for _ in range(5):
            self.assertTrue(self.w.tick()["warming_up"])
        self.assertFalse(any(isinstance(e, tuple) and e[1] == "stop" for e in self.w.events))
        self.w.uptime += 31
        self.assertEqual(self.w.tick()["failures"], 1)

    def test_native_restart_cancelled_if_confirmation_recovers(self) -> None:
        self.w.activate()
        self.w.tick()
        self.w.tick()
        self.w.health = mock.Mock(
            side_effect=[
                {"healthy": False, "errors": ["unavailable"]},
                {"healthy": True, "errors": []},
            ]
        )
        self.assertTrue(self.w.tick()["restart_cancelled"])
        self.assertFalse(any(isinstance(e, tuple) and e[1] == "stop" for e in self.w.events))

    def test_stale_agent_target_keeps_native_untouched(self) -> None:
        self.w.activate()
        self.w.events.clear()
        self.w.agent = "k3s-agent.service"
        self.w.service_installed = lambda unit: True
        with self.assertRaisesRegex(RuntimeError, "Legacy agent"):
            self.w.failback()
        self.assertEqual(self.w.events, [])
        self.assertTrue((self.w.state / "active").exists())

    def test_missing_target_keeps_native_untouched(self) -> None:
        self.w.activate()
        self.w.events.clear()
        self.w.service_installed = lambda unit: False
        with self.assertRaisesRegex(RuntimeError, "not installed"):
            self.w.failback()
        self.assertEqual(self.w.events, [])

    def test_failed_kubernetes_start_restores_native_immediately(self) -> None:
        self.w.activate()
        command = self.w.command

        def failed(*args):
            if args == ("systemctl", "start", self.w.agent):
                raise RuntimeError("start failed")
            return command(*args)

        self.w.command = failed
        with self.assertRaisesRegex(RuntimeError, "start failed"):
            self.w.failback()
        self.assertEqual(self.w.running, set(MODULE.NATIVE_UNITS))
        self.assertTrue((self.w.state / "active").exists())

    def test_failure_receipt_is_durable(self) -> None:
        self.w.tick()
        receipt = json.loads((self.w.state / "last_failure.json").read_text())
        self.assertEqual(receipt["mode"], "kubernetes")
        self.assertFalse(receipt["healthy"])
        self.assertEqual((self.w.state / "last_failure.json").stat().st_mode & 0o777, 0o600)


class ServiceIdentityContractTests(unittest.TestCase):
    def test_python_and_ansible_defaults_use_current_server(self) -> None:
        self.assertEqual(MODULE.Watchdog({}).agent, "k3s.service")
        import yaml

        root = SOURCE.parents[4]
        defaults = yaml.safe_load(
            (root / "ansible/roles/vpn_failover/defaults/main.yml").read_text()
        )
        self.assertEqual(defaults["vpn_failover_k3s_unit"], "k3s.service")
        self.assertEqual(
            set(defaults["vpn_failover_fenced_units"]), {"k3s.service", "k3s-agent.service"}
        )


if __name__ == "__main__":
    unittest.main()
