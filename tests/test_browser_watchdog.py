import importlib.util
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('browser_watchdog', Path(__file__).resolve().parents[1] / 'charts/open-terminal/files/browser_watchdog.py')
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def process(pid=10, ppid=1, start=100, executable='chrome', args=None):
    if args is None:
        args = ('chrome', '--headless=new', '--remote-debugging-pipe', '--user-data-dir=/tmp/playwright_chromiumdev_profile-abc')
    return MODULE.Process(pid, ppid, start, executable, args)


class BrowserWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.guard = MODULE.Watchdog(lifetime=10, grace=5, ticks=100, send=lambda identity, sig: self.sent.append((identity, sig)))

    def step(self, now, *items):
        self.guard.step({p.pid: p for p in items}, now)

    def test_only_specific_headless_playwright_roots_match(self):
        self.assertTrue(MODULE.is_test_browser(process()))
        self.assertTrue(MODULE.is_test_browser(process(executable='chrome-headless-shell')))
        for item in (
            process(executable='node'),
            process(args=('chrome', '--headless', '--remote-debugging-pipe', '--user-data-dir=/home/user/profile')),
            process(args=('chrome', '--headless', '--user-data-dir=/tmp/playwright_test')),
            process(args=('chrome', '--remote-debugging-pipe', '--user-data-dir=/tmp/playwright_test')),
            process(args=process().args + ('--type=renderer',)),
        ):
            self.assertFalse(MODULE.is_test_browser(item))

    def test_deadline_uses_original_process_start(self):
        self.step(10.9, process())
        self.assertEqual(self.sent, [])
        self.step(11, process())
        self.assertEqual(self.sent, [((10, 100), signal.SIGTERM)])

    def test_existing_old_browser_is_expired_on_first_scan(self):
        self.step(1000, process())
        self.assertEqual(self.sent, [((10, 100), signal.SIGTERM)])

    def test_descendants_follow_parentage_independent_of_sessions(self):
        child = process(11, 10, executable='chrome', args=('--type=renderer',))
        grandchild = process(12, 11, executable='helper', args=())
        unrelated = process(13, 1, executable='node', args=())
        self.step(11, process(), child, grandchild, unrelated)
        self.assertEqual({identity[0] for identity, sig in self.sent}, {10, 11, 12})

    def test_reparented_descendant_remains_owned(self):
        child = process(11, 10, executable='chrome', args=('--type=renderer',))
        self.step(5, process(), child)
        orphan = process(11, 1, executable='chrome', args=('--type=renderer',))
        self.step(11, orphan)
        self.assertEqual(self.sent, [((11, 100), signal.SIGTERM)])

    def test_reused_pid_and_its_children_are_not_killed(self):
        self.step(5, process())
        replacement = process(start=600, executable='node', args=())
        child = process(11, 10, start=700, executable='worker', args=())
        self.step(12, replacement, child)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.guard.browsers, {})

    def test_term_then_grace_then_kill(self):
        self.step(11, process())
        self.step(15.9, process())
        self.assertEqual(len(self.sent), 1)
        self.step(16, process())
        self.assertEqual(self.sent[-1], ((10, 100), signal.SIGKILL))

    def test_new_descendant_during_grace_is_killed(self):
        self.step(11, process())
        child = process(11, 10, start=1200, executable='worker', args=())
        self.step(16, process(), child)
        self.assertIn(((11, 1200), signal.SIGKILL), self.sent)

    def test_exited_processes_are_forgotten(self):
        self.step(11, process())
        self.step(16)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.guard.browsers, {})

    def test_proc_parser_handles_spaces_and_parentheses_in_process_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / '10'
            entry.mkdir()
            fields = ['S', '7'] + ['0'] * 17 + ['12345'] + ['0'] * 5
            (entry / 'stat').write_text('10 (chrome worker (test)) ' + ' '.join(fields))
            (entry / 'cmdline').write_bytes(b'chrome\0--headless\0')
            (entry / 'exe').symlink_to('/opt/chrome')
            actual = MODULE.read_process(10, root)
            self.assertEqual(actual, process(10, 7, 12345, args=('chrome', '--headless')))

    def test_signal_revalidates_identity_before_using_pidfd(self):
        with patch.object(MODULE.os, 'pidfd_open', return_value=99, create=True), patch.object(MODULE.os, 'close') as close, patch.object(MODULE, 'read_process', return_value=process(start=999)), patch.object(MODULE.signal, 'pidfd_send_signal', create=True) as send:
            self.assertFalse(MODULE.signal_process((10, 100), signal.SIGKILL))
            send.assert_not_called()
            close.assert_called_once_with(99)

    def test_permission_denied_opening_pidfd_is_nonfatal(self):
        with patch.object(MODULE.os, 'pidfd_open', side_effect=PermissionError, create=True), self.assertLogs(level='WARNING'):
            self.assertFalse(MODULE.signal_process((10, 100), signal.SIGTERM))

    def test_permission_denied_signaling_is_nonfatal_and_closes_fd(self):
        with patch.object(MODULE.os, 'pidfd_open', return_value=99, create=True), patch.object(MODULE.os, 'close') as close, patch.object(MODULE, 'read_process', return_value=process()), patch.object(MODULE.signal, 'pidfd_send_signal', side_effect=PermissionError, create=True), self.assertLogs(level='WARNING'):
            self.assertFalse(MODULE.signal_process((10, 100), signal.SIGTERM))
            close.assert_called_once_with(99)

    def test_pidfd_is_used_for_matching_process(self):
        with patch.object(MODULE.os, 'pidfd_open', return_value=99, create=True), patch.object(MODULE.os, 'close') as close, patch.object(MODULE, 'read_process', return_value=process()), patch.object(MODULE.signal, 'pidfd_send_signal', create=True) as send:
            self.assertTrue(MODULE.signal_process((10, 100), signal.SIGTERM))
            send.assert_called_once_with(99, signal.SIGTERM)
            close.assert_called_once_with(99)


if __name__ == '__main__':
    unittest.main()
