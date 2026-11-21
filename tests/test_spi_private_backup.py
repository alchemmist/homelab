"""Tests for SPI private backup procedures."""

import importlib.util
import os
import stat
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/n8n/spi_private_backup.py"

PRIVATE_BACKUP_FILE_MODE = 0o600
MAX_READ_DEADLINE_SECONDS = 3
TIMER_INITIAL_SECONDS = 30
TIMER_INTERVAL_SECONDS = 7


class BackupTests(unittest.TestCase):
    """Verify SPI private backup streaming and cleanup."""
    def test_private_stream_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "source"
            dst = Path(d) / "host"
            c = sqlite3.connect(src)
            c.execute("CREATE TABLE ledger(value TEXT)")
            c.execute("INSERT INTO ledger VALUES('unchanged')")
            c.commit()
            c.close()
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--source",
                        str(src),
                        "--private-pvc-directory",
                        d,
                    ],
                    stdout=f,
                    check=True,
                )
            assert stat.S_IMODE(dst.stat().st_mode) == PRIVATE_BACKUP_FILE_MODE
            c = sqlite3.connect(dst)
            assert c.execute("SELECT * FROM ledger").fetchall() == [("unchanged",)]
            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            c.close()
            assert list(Path(d).glob(".spi-prechange-*")) == []

    def test_bound_failure_cleans(self) -> None:
        spec = importlib.util.spec_from_file_location("backup", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "source"
            c = sqlite3.connect(src)
            c.execute("CREATE TABLE x(a)")
            c.close()
            with self.assertRaises(RuntimeError):
                m.backup(str(src), d, max_bytes=1)
            assert list(Path(d).glob(".spi-prechange-*")) == []


class BackupDeadlineTests(unittest.TestCase):
    """Confirm backup failures correctly trigger their deadline kind."""
    def run_failure(self, kind) -> None:
        import time

        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "source"
            c = sqlite3.connect(src)
            c.execute("CREATE TABLE x(a BLOB)")
            c.execute("INSERT INTO x VALUES(zeroblob(4194304))")
            c.commit()
            if kind == "busy":
                c.execute("BEGIN EXCLUSIVE")
            if kind == "open":
                src = Path(d) / "missing"
            cmd = [
                sys.executable,
                str(SCRIPT),
                "--source",
                str(src),
                "--private-pvc-directory",
                d,
                "--deadline-seconds",
                "0.4",
            ]
            started = time.monotonic()
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                if kind == "broken":
                    proc.stdout.close()
                # Deliberately never read stdout before exit: actual full pipe.
                status = proc.wait(timeout=4)
                assert status != 0
                assert time.monotonic() - started < MAX_READ_DEADLINE_SECONDS
                assert (
                    proc.stderr.read()
                    == b"BACKUP_FAILED: output invalid; delete private host file\n"
                )
                assert list(Path(d).glob(".spi-prechange-*")) == []
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=2)
                if not proc.stdout.closed:
                    proc.stdout.close()
                proc.stderr.close()
                c.close()

    def test_actual_blocked_consumer(self) -> None:
        self.run_failure("blocked")

    def test_broken_pipe(self) -> None:
        self.run_failure("broken")

    def test_busy_source(self) -> None:
        self.run_failure("busy")

    def test_connection_open_cleanup(self) -> None:
        self.run_failure("open")

    def test_slow_integrity_deadline(self) -> None:
        # Real subprocess and real SQLite VM; progress callback intentionally
        # sleeps while integrity is running, not a mocked monotonic clock.
        code = """import importlib.util,sqlite3,sys,time
spec=importlib.util.spec_from_file_location('b',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=sqlite3.connect
class Slow(sqlite3.Connection):
 def set_progress_handler(self,callback,n):
  def slow():
   time.sleep(.03)
   return callback()
  super().set_progress_handler(slow,1)
def connect(*a,**kw):return original(*a,**kw,factory=Slow)
m.sqlite3.connect=connect
try:m.backup(sys.argv[2],sys.argv[3],deadline_seconds=.4)
except Exception:sys.exit(1)
"""
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "source"
            c = sqlite3.connect(src)
            c.execute("CREATE TABLE x(a)")
            c.executemany("INSERT INTO x VALUES(?)", [(i,) for i in range(100)])
            c.commit()
            c.close()
            result = subprocess.run(
                [sys.executable, "-c", code, str(SCRIPT), str(src), d],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=4,
            )
            assert result.returncode != 0
            assert list(Path(d).glob(".spi-prechange-*")) == []

    def test_alarm_restored_and_pvc_private(self) -> None:
        import signal
        from unittest.mock import patch

        spec = importlib.util.spec_from_file_location("backup", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        old = signal.getsignal(signal.SIGALRM)
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "source"
            c = sqlite3.connect(src)
            c.execute("CREATE TABLE x(a)")
            c.close()
            original = m.sqlite3.connect

            def checked(path, *a, **kw):
                if not kw.get("uri"):
                    assert stat.S_IMODE(Path(path).stat().st_mode) == PRIVATE_BACKUP_FILE_MODE
                    raise OSError("synthetic destination open failure")
                return original(path, *a, **kw)

            with patch.object(m.sqlite3, "connect", checked):
                with self.assertRaises(OSError):
                    m.backup(str(src), d)
            assert list(Path(d).glob(".spi-prechange-*")) == []
            assert signal.getsignal(signal.SIGALRM) == old
            assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


class CleanupBoundaryTests(unittest.TestCase):
    """Check real ownership and close-failure cleanup boundaries."""
    def test_real_ownership_and_close_failures(self) -> None:
        import signal
        from unittest.mock import patch

        spec = importlib.util.spec_from_file_location("backup", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        create = m.tempfile.mkstemp
        connect = m.sqlite3.connect
        count: list[int] = [0]
        for boundary in ("creation", "first-close", "second-close", "pending-close"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as d:
                src = Path(d) / "source"
                c = sqlite3.connect(src)
                c.execute("CREATE TABLE x(a)")
                c.close()
                old = signal.getsignal(signal.SIGALRM)
                count[0] = 0

                def owned(*a: object, boundary: str = boundary, **kw: object) -> tuple[int, str]:
                    result: tuple[int, str] = create(*a, **kw)
                    for suffix in ("-wal", "-shm", "-journal"):
                        Path(result[1] + suffix).touch(mode=0o600)
                    if boundary == "creation":
                        os.kill(os.getpid(), signal.SIGALRM)
                    return result

                class Conn(sqlite3.Connection):
                    def close(self, boundary: str = boundary) -> None:
                        super().close()
                        count[0] += 1
                        if boundary == "pending-close":
                            os.kill(os.getpid(), signal.SIGALRM)
                        if count[0] == (2 if boundary == "second-close" else 1):
                            raise TimeoutError("synthetic close failure")

                def connected(*a, **kw):
                    return connect(*a, **kw, factory=Conn)

                with (
                    patch.object(m.tempfile, "mkstemp", owned),
                    patch.object(m.sqlite3, "connect", connected),
                ):
                    with self.assertRaises(TimeoutError):
                        m.backup(str(src), d)
                assert list(Path(d).glob(".spi-prechange-*")) == []
                assert signal.getsignal(signal.SIGALRM) == old
                assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)

    def test_prior_periodic_timer_restored_on_open_failure(self) -> None:
        import signal

        spec = importlib.util.spec_from_file_location("backup", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        handler = signal.getsignal(signal.SIGALRM)
        timer = signal.getitimer(signal.ITIMER_REAL)

        def caller(*args):
            pass

        try:
            signal.signal(signal.SIGALRM, caller)
            signal.setitimer(signal.ITIMER_REAL, TIMER_INITIAL_SECONDS, TIMER_INTERVAL_SECONDS)
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(sqlite3.OperationalError):
                    m.backup(str(Path(d) / "absent"), d)
                assert list(Path(d).glob(".spi-prechange-*")) == []
            assert signal.getsignal(signal.SIGALRM) is caller
            remaining, interval = signal.getitimer(signal.ITIMER_REAL)
            assert remaining > TIMER_INITIAL_SECONDS - 5
            assert remaining <= TIMER_INITIAL_SECONDS
            assert interval == TIMER_INTERVAL_SECONDS
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, *timer)
