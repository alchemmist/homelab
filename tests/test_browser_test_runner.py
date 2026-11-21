"""Tests for the open-terminal browser test runner."""

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "charts/open-terminal/files/browser_test_runner.py"


@unittest.skipUnless(
    sys.platform == "linux", "Linux process ownership and subreaper semantics required"
)
class BrowserTestRunnerTests(unittest.TestCase):
    """Exercise the browser test runner's process and lifecycle handling."""

    def setUp(self) -> None:
        """Create a scratch directory, pidfile and process registries."""
        self.directory = tempfile.TemporaryDirectory()
        self.pidfile = Path(self.directory.name) / "child.pid"
        self.runners: list[subprocess.Popen[bytes]] = []
        self.children: list[subprocess.Popen[bytes]] = []

    def tearDown(self) -> None:
        """Kill and reap every spawned runner and child process."""
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

    def launch(self, body, timeout=5) -> subprocess.Popen[bytes]:
        """Start the runner wrapping a python -c body and register it."""
        process = subprocess.Popen(
            [
                sys.executable,
                str(RUNNER),
                "--timeout",
                str(timeout),
                "--",
                sys.executable,
                "-c",
                body,
            ]
        )
        self.runners.append(process)
        return process

    def child_code(self) -> str:
        """Return child code that ignores SIGTERM and records its pid."""
        return f'import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open({str(self.pidfile)!r}, "w").write(str(os.getpid())); time.sleep(60)'

    def parent_code(self, tail: str) -> str:
        """Return parent code spawning the detached child then the tail."""
        return (
            "import subprocess,sys,time,pathlib; "
            f'subprocess.Popen([sys.executable,"-c",{self.child_code()!r}],start_new_session=True); '
            f"p=pathlib.Path({str(self.pidfile)!r}); "
            "\nwhile not p.exists(): time.sleep(.01)\n" + tail
        )

    def assert_child_gone(self) -> None:
        """Assert the recorded child pid no longer has a proc entry."""
        pid = int(self.pidfile.read_text())
        assert not Path(f"/proc/{pid}").exists(), f"child {pid} survived runner exit"

    def test_detached_child_cleaned_after_success(self) -> None:
        """A successful exit still cleans the detached child."""
        process = self.launch(self.parent_code("sys.exit(0)"))
        assert process.wait(timeout=10) == 0
        self.assert_child_gone()

    def test_detached_child_cleaned_after_failure(self) -> None:
        """A failing exit still cleans the detached child."""
        process = self.launch(self.parent_code("sys.exit(7)"))
        exit_failure_code = 7
        assert process.wait(timeout=10) == exit_failure_code
        self.assert_child_gone()

    def test_timeout_cleans_child_and_preserves_unrelated_process(self) -> None:
        """Timeout kills the child but leaves unrelated processes alone."""
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.children.append(unrelated)
        process = self.launch(self.parent_code("time.sleep(60)"), timeout=0.5)
        # The runner exits with the 124 timeout status on its own cleanup path.
        timeout_exit_code = 124
        assert process.wait(timeout=10) == timeout_exit_code
        self.assert_child_gone()
        assert unrelated.poll() is None

    def test_sigterm_cleans_detached_child(self) -> None:
        """SIGTERM to the runner also cleans the detached child."""
        process = self.launch(self.parent_code("time.sleep(60)"))
        deadline = time.monotonic() + 5
        while not self.pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert self.pidfile.exists()
        process.terminate()
        # 128 + SIGTERM(15): the parent reports the signalled child.
        sigterm_exit_code = 143
        assert process.wait(timeout=10) == sigterm_exit_code
        self.assert_child_gone()

    def test_double_fork_adopted_before_first_snapshot(self) -> None:
        """Double-forked children are adopted before the first snapshot."""
        body = (
            "import os,sys,time,pathlib; "
            f"p=pathlib.Path({str(self.pidfile)!r})\n"
            "if os.fork():\n while not p.exists(): time.sleep(.001)\n sys.exit(0)\n"
            "os.setsid()\n"
            "if os.fork(): os._exit(0)\n" + self.child_code()
        )
        process = self.launch(body)
        assert process.wait(timeout=10) == 0
        self.assert_child_gone()


if __name__ == "__main__":
    unittest.main()
