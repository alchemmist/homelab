import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'ansible/roles/vpn_failover/files/vpn_failover.py'
SPEC = importlib.util.spec_from_file_location('vpn_failover', SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeWatchdog(MODULE.Watchdog):
    def __init__(self, directory):
        super().__init__({'state_dir': directory, 'listen_ports': [], 'failure_threshold': 4})
        self.good = False
        self.uptime = 300
        self.events = []
        self.running = set()
        self.stuck = False
        self.ports = []
        self.invalid = False

    def clock(self):
        return 'boot-one', self.uptime

    def health(self):
        return {'healthy': self.good, 'errors': [] if self.good else ['unavailable']}

    def preflight(self):
        if self.invalid:
            raise RuntimeError('Missing assets')

    def fence(self):
        self.events.append('fence')
        if self.stuck:
            raise RuntimeError('Cannot fence')

    def guard(self):
        if not (self.state / 'active').exists() or self.stuck:
            raise RuntimeError('Unsafe start')

    def occupied(self):
        return self.ports

    def service_active(self, unit):
        return unit in self.running

    def command(self, *args):
        self.events.append(args)
        if args[1] == 'start':
            self.running.add(args[2])
        elif args[1] == 'stop':
            self.running.discard(args[2])
        return ''


class FailoverTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.watchdog = FakeWatchdog(self.directory.name)

    def test_boot_grace_avoids_failure_counting(self):
        self.watchdog.uptime = 20
        self.assertEqual(self.watchdog.tick(), {'mode': 'grace'})
        self.assertFalse((self.watchdog.state / 'failures.json').exists())

    def test_four_failures_required_and_latch_persisted(self):
        for count in range(1, 4):
            self.assertEqual(self.watchdog.tick()['failures'], count)
            self.assertFalse(self.watchdog.running)
        self.assertEqual(self.watchdog.tick()['mode'], 'fallback')
        self.assertTrue((self.watchdog.state / 'active').exists())
        self.assertEqual(self.watchdog.events[0], 'fence')
        self.assertEqual(self.watchdog.running, set(MODULE.NATIVE_UNITS))

    def test_recovery_resets_consecutive_errors(self):
        self.watchdog.tick()
        self.watchdog.good = True
        self.assertEqual(self.watchdog.tick()['failures'], 0)
        self.watchdog.good = False
        self.assertEqual(self.watchdog.tick()['failures'], 1)

    def test_failed_fencing_preserves_latch_without_native_start(self):
        self.watchdog.stuck = True
        with self.assertRaises(RuntimeError):
            self.watchdog.activate()
        self.assertTrue((self.watchdog.state / 'active').exists())
        self.assertFalse(self.watchdog.running)
        self.watchdog.stuck = False
        self.watchdog.tick()
        self.assertEqual(self.watchdog.running, set(MODULE.NATIVE_UNITS))

    def test_missing_assets_do_not_fence_working_kubernetes(self):
        self.watchdog.invalid = True
        with self.assertRaises(RuntimeError):
            self.watchdog.activate()
        self.assertFalse((self.watchdog.state / 'active').exists())
        self.assertEqual(self.watchdog.events, [])

    def test_occupied_ports_prevent_first_native_start(self):
        self.watchdog.ports = [('tcp', 443)]
        with self.assertRaises(RuntimeError):
            self.watchdog.activate()
        self.assertFalse(self.watchdog.running)
        self.assertTrue((self.watchdog.state / 'active').exists())

    def test_healthy_fallback_does_not_automatically_fail_back(self):
        self.watchdog.activate()
        self.watchdog.good = True
        self.watchdog.tick()
        self.assertTrue((self.watchdog.state / 'active').exists())
        self.assertNotIn(self.watchdog.agent, self.watchdog.running)

    def test_maintenance_inhibit_prevents_actions(self):
        (self.watchdog.state / 'inhibit').touch()
        self.assertEqual(self.watchdog.tick(), {'mode': 'inhibited'})
        self.assertEqual(self.watchdog.events, [])

    def test_failback_keeps_fence_when_native_ports_remain(self):
        self.watchdog.activate()
        self.watchdog.ports = [('tcp', 443)]
        with self.assertRaises(RuntimeError):
            self.watchdog.failback()
        self.assertTrue((self.watchdog.state / 'active').exists())
        self.assertNotIn(self.watchdog.agent, self.watchdog.running)

    def test_failback_releases_latch_after_stopping_native_and_adds_grace(self):
        self.watchdog.activate()
        self.watchdog.failback()
        self.assertFalse((self.watchdog.state / 'active').exists())
        self.assertEqual(self.watchdog.running, {self.watchdog.agent})
        self.assertEqual(self.watchdog.tick(), {'mode': 'grace'})

    def test_new_boot_resets_old_failures(self):
        self.watchdog.write('failures.json', {'boot_id': 'old', 'failures': 100, 'grace_until': 999999})
        self.assertEqual(self.watchdog.tick()['failures'], 1)

    def test_partial_activation_does_not_restart_running_units(self):
        self.watchdog.activate()
        self.watchdog.running.remove(MODULE.NATIVE_UNITS[-1])
        self.watchdog.events.clear()
        self.watchdog.tick()
        self.assertEqual(self.watchdog.events, ['fence', ('systemctl', 'start', MODULE.NATIVE_UNITS[-1])])

    def test_partial_activation_refuses_inactive_unit_port_conflict(self):
        self.watchdog.activate()
        unit = MODULE.NATIVE_UNITS[-1]
        self.watchdog.running.remove(unit)
        self.watchdog.config['native_unit_ports'] = {unit: [{'protocol': 'tcp', 'port': 443}]}
        self.watchdog.ports = [('tcp', 443)]
        with self.assertRaises(RuntimeError):
            self.watchdog.tick()
        self.assertNotIn(unit, self.watchdog.running)

    def test_unhealthy_active_native_services_restart_after_threshold(self):
        self.watchdog.activate()
        self.watchdog.events.clear()
        self.watchdog.tick()
        self.watchdog.tick()
        self.assertFalse(any(isinstance(event, tuple) and event[1] == 'stop' for event in self.watchdog.events))
        self.assertTrue(self.watchdog.tick()['restarted'])
        self.assertEqual(self.watchdog.running, set(MODULE.NATIVE_UNITS))
        self.assertTrue((self.watchdog.state / 'active').exists())

    def test_native_recovery_health_resets_restart_counter(self):
        self.watchdog.activate()
        self.watchdog.tick()
        self.watchdog.good = True
        self.assertEqual(self.watchdog.tick()['failures'], 0)
        self.watchdog.good = False
        self.assertEqual(self.watchdog.tick()['failures'], 1)

    def test_pidfd_signal_targets_verified_kubernetes_process(self):
        with mock.patch.object(MODULE.os, 'pidfd_open', return_value=91, create=True), mock.patch.object(MODULE.signal, 'pidfd_send_signal', create=True) as send, mock.patch.object(MODULE.os, 'close') as close, mock.patch.object(MODULE.Path, 'read_text', return_value='0::/kubepods/pod-one'):
            self.watchdog.terminate(123, MODULE.signal.SIGTERM)
        send.assert_called_once_with(91, MODULE.signal.SIGTERM)
        close.assert_called_once_with(91)

    def test_changed_process_cgroup_refuses_signal(self):
        with mock.patch.object(MODULE.os, 'pidfd_open', return_value=91, create=True), mock.patch.object(MODULE.signal, 'pidfd_send_signal', create=True) as send, mock.patch.object(MODULE.os, 'close'), mock.patch.object(MODULE.Path, 'read_text', return_value='0::/system.slice/ssh.service'):
            with self.assertRaises(RuntimeError):
                self.watchdog.terminate(123, MODULE.signal.SIGTERM)
        send.assert_not_called()


class KubernetesFencingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.watchdog = MODULE.Watchdog({'state_dir': self.directory.name, 'agent_unit': 'k3s.service'})
        self.loads = {'k3s-agent.service': 'loaded', 'k3s.service': 'loaded'}
        self.active = {'k3s-agent.service', 'k3s.service'}
        self.commands = []
        self.watchdog.command = self.command

    def command(self, *args):
        self.commands.append(args)
        if args[1] == 'show':
            if args[3] == '--property=LoadState':
                return self.loads[args[2]]
            return 'active' if args[2] in self.active else 'inactive'
        if args[1] == 'stop':
            self.active.discard(args[2])

    def test_fence_stops_both_installed_units(self):
        with mock.patch.object(self.watchdog, 'processes', return_value=[]):
            self.watchdog.fence()
        self.assertFalse(self.active)
        self.assertIn(('systemctl', 'stop', 'k3s-agent.service'), self.commands)
        self.assertIn(('systemctl', 'stop', 'k3s.service'), self.commands)

    def test_missing_agent_is_ignored_but_server_is_stopped(self):
        self.loads['k3s-agent.service'] = 'not-found'
        self.active = {'k3s.service'}
        with mock.patch.object(self.watchdog, 'processes', return_value=[]):
            self.watchdog.fence()
        self.assertNotIn(('systemctl', 'stop', 'k3s-agent.service'), self.commands)
        self.assertFalse(self.active)

    def test_active_server_blocks_native_even_when_agent_is_absent(self):
        (self.watchdog.state / 'active').touch()
        self.loads['k3s-agent.service'] = 'not-found'
        self.active = {'k3s.service'}
        with mock.patch.object(self.watchdog, 'processes', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, 'verified Kubernetes fencing'):
                self.watchdog.guard()

    def test_unknown_load_state_fails_closed(self):
        self.loads['k3s.service'] = 'error'
        with self.assertRaisesRegex(RuntimeError, 'Cannot verify systemd unit'):
            self.watchdog.fence()
        self.assertFalse(any(args[1] == 'stop' for args in self.commands))

    def test_fence_refuses_service_still_active(self):
        with mock.patch.object(self.watchdog, 'service_active', return_value=True), mock.patch.object(self.watchdog, 'processes') as processes:
            with self.assertRaisesRegex(RuntimeError, 'did not stop'):
                self.watchdog.fence()
        processes.assert_not_called()

    def test_server_and_agent_cgroups_are_both_fenced(self):
        for unit in self.watchdog.fenced_units:
            with self.subTest(unit=unit), mock.patch.object(MODULE.os, 'pidfd_open', return_value=91, create=True), mock.patch.object(MODULE.signal, 'pidfd_send_signal', create=True) as send, mock.patch.object(MODULE.os, 'close'), mock.patch.object(MODULE.Path, 'read_text', return_value='0::/system.slice/' + unit):
                self.watchdog.terminate(123, MODULE.signal.SIGTERM)
                send.assert_called_once_with(91, MODULE.signal.SIGTERM)

    def test_failback_starts_only_configured_server(self):
        (self.watchdog.state / 'active').touch()
        with mock.patch.object(self.watchdog, 'processes', return_value=[]), mock.patch.object(self.watchdog, 'occupied', return_value=[]), mock.patch.object(self.watchdog, 'clock', return_value=('boot', 300)):
            self.watchdog.failback()
        self.assertEqual([args for args in self.commands if args[1] == 'start'], [('systemctl', 'start', 'k3s.service')])
        self.assertFalse((self.watchdog.state / 'active').exists())


if __name__ == '__main__':
    unittest.main()
