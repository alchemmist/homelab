import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[1] / 'charts/open-terminal/files/browser_test_runner.py'


@unittest.skipUnless(sys.platform == 'linux', 'Linux process ownership and subreaper semantics required')
class BrowserTestRunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.pidfile = Path(self.directory.name) / 'child.pid'
        self.runners = []
        self.children = []

    def tearDown(self):
        for process in self.runners + self.children:
            if process.poll() is None:
                process.kill()
            process.wait()
        if self.pidfile.exists():
            try:
                os.kill(int(self.pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.directory.cleanup()

    def launch(self, body, timeout=5):
        process = subprocess.Popen([sys.executable, str(RUNNER), '--timeout', str(timeout), '--', sys.executable, '-c', body])
        self.runners.append(process)
        return process

    def child_code(self):
        return f'import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open({str(self.pidfile)!r}, "w").write(str(os.getpid())); time.sleep(60)'

    def parent_code(self, tail):
        return (
            'import subprocess,sys,time,pathlib; '
            f'subprocess.Popen([sys.executable,"-c",{self.child_code()!r}],start_new_session=True); '
            f'p=pathlib.Path({str(self.pidfile)!r}); '
            '\nwhile not p.exists(): time.sleep(.01)\n' + tail
        )

    def assert_child_gone(self):
        pid = int(self.pidfile.read_text())
        self.assertFalse(Path(f'/proc/{pid}').exists(), f'child {pid} survived runner exit')

    def test_detached_child_cleaned_after_success(self):
        process = self.launch(self.parent_code('sys.exit(0)'))
        self.assertEqual(process.wait(timeout=10), 0)
        self.assert_child_gone()

    def test_detached_child_cleaned_after_failure(self):
        process = self.launch(self.parent_code('sys.exit(7)'))
        self.assertEqual(process.wait(timeout=10), 7)
        self.assert_child_gone()

    def test_timeout_cleans_child_and_preserves_unrelated_process(self):
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.children.append(unrelated)
        process = self.launch(self.parent_code('time.sleep(60)'), timeout=.5)
        self.assertEqual(process.wait(timeout=10), 124)
        self.assert_child_gone()
        self.assertIsNone(unrelated.poll())

    def test_sigterm_cleans_detached_child(self):
        process = self.launch(self.parent_code('time.sleep(60)'))
        deadline = time.monotonic() + 5
        while not self.pidfile.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(self.pidfile.exists())
        process.terminate()
        self.assertEqual(process.wait(timeout=10), 143)
        self.assert_child_gone()

    def test_double_fork_adopted_before_first_snapshot(self):
        body = (
            'import os,sys,time,pathlib; '
            f'p=pathlib.Path({str(self.pidfile)!r})\n'
            'if os.fork():\n while not p.exists(): time.sleep(.001)\n sys.exit(0)\n'
            'os.setsid()\n'
            'if os.fork(): os._exit(0)\n'
            + self.child_code()
        )
        process = self.launch(body)
        self.assertEqual(process.wait(timeout=10), 0)
        self.assert_child_gone()


if __name__ == '__main__':
    unittest.main()
