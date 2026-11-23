#!/usr/bin/env python3
"""Private CLI-only online backup. Failed/truncated stdout MUST be deleted.

POSIX main-thread deadline assumes normally interruptible OS I/O; no guarantee
is possible for uninterruptible kernel I/O. Never invoke in HTTP worker threads.
"""

import argparse
import os
import signal
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable
from typing import NamedTuple


class _BackupContext(NamedTuple):
    """Mutable resource slots and prior signal state for deadline teardown."""

    fd: int | None
    path: str | None
    dst: sqlite3.Connection | None
    src: sqlite3.Connection | None
    old_handler: signal.Handlers
    old_timer: tuple[float, float]
    start: float


def _open_connections(
    source: str, path: str, deadline_seconds: float
) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Open the read-only source and private destination under blocked SIGALRM."""
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
    try:
        src = sqlite3.connect(
            "file:" + source + "?mode=ro", uri=True, timeout=min(0.05, deadline_seconds)
        )
        dst = sqlite3.connect(path, timeout=min(0.05, deadline_seconds))
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
    return src, dst


def _emit_backup(path: str, max_bytes: int, check: Callable[[], None]) -> None:
    """Stream the verified private backup to stdout in bounded deadline chunks."""
    if os.path.getsize(path) > max_bytes:
        msg = "backup size exceeded"
        raise RuntimeError(msg)
    with open(path, "rb") as f:
        while True:
            check()
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
    check()


def _close_resources(context: _BackupContext) -> list[BaseException]:
    """Close any open connections and the staging descriptor."""
    errors: list[BaseException] = []
    for conn in (context.dst, context.src):
        try:
            if conn is not None:
                conn.close()
        except BaseException as exc:
            errors.append(exc)
    if context.fd is not None:
        try:
            os.close(context.fd)
        except BaseException as exc:
            errors.append(exc)
    return errors


def _unlink_output(path: str | None) -> list[BaseException]:
    """Unlink the failed backup output and its SQLite sidecar files."""
    errors: list[BaseException] = []
    if not path:
        return errors
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass
        except BaseException as exc:
            errors.append(exc)
    return errors


def _restore_alarm(mask: set[signal.Signals], context: _BackupContext) -> None:
    """Drain the one-shot alarm, then restore the prior handler and timer."""
    if signal.SIGALRM in signal.sigpending():
        signal.sigwait({signal.SIGALRM})
    signal.signal(signal.SIGALRM, context.old_handler)
    if context.old_timer[0]:
        signal.setitimer(
            signal.ITIMER_REAL,
            max(0.000001, context.old_timer[0] - (time.monotonic() - context.start)),
            context.old_timer[1],
        )
    signal.pthread_sigmask(signal.SIG_SETMASK, mask)


def _progress_guard(
    check: Callable[[], None], page_size: object, max_bytes: object
) -> Callable[[int, int, int], None]:
    """Return the deadline- and size-enforcing progress callback."""

    def progress(status, remaining, total) -> None:
        check()
        if total * page_size > max_bytes:
            msg = "backup size exceeded"
            raise RuntimeError(msg)

    return progress


def _alarm_expired(*args: object) -> None:
    """Fire the one-shot SIGALRM as a hard deadline."""
    signal.setitimer(signal.ITIMER_REAL, 0)
    msg = "backup deadline exceeded"
    raise TimeoutError(msg)


def _deadline_check(start: float, deadline_seconds: float) -> Callable[[], None]:
    """Return the periodic watchdog used across streaming boundaries."""

    def check() -> None:
        if time.monotonic() - start >= deadline_seconds:
            _alarm_expired()

    return check


def backup(source, directory, max_bytes=512 * 1024 * 1024, deadline_seconds=60) -> None:
    """Stream a consistent SQLite backup to stdout within size and time bounds."""
    if os.environ.get("SPI_POSTGRES_URL"):
        msg = "SQLite is not the active SPI database"
        raise ValueError(msg)
    if deadline_seconds <= 0 or max_bytes <= 0:
        msg = "invalid bounds"
        raise ValueError(msg)
    start = time.monotonic()
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    path = None
    fd = None
    src = None
    dst = None

    check = _deadline_check(start, deadline_seconds)
    signal.signal(signal.SIGALRM, _alarm_expired)
    signal.setitimer(signal.ITIMER_REAL, deadline_seconds)
    try:
        # Block return/assignment boundaries until ownership is recorded.
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        try:
            fd, path = tempfile.mkstemp(prefix=".spi-prechange-", suffix=".sqlite", dir=directory)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        os.close(fd)
        fd = None
        src, dst = _open_connections(source, path, deadline_seconds)
        page_size = src.execute("PRAGMA page_size").fetchone()[0]
        src.backup(
            dst,
            pages=128,
            progress=_progress_guard(check, page_size, max_bytes),
            sleep=0.01,
        )
        dst.set_progress_handler(lambda: int(time.monotonic() - start >= deadline_seconds), 100)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            msg = "backup integrity failure"
            raise RuntimeError(msg)
        check()
        dst.close()
        dst = None
        src.close()
        src = None
        _emit_backup(path, max_bytes, check)
    finally:
        # Cancel before cleanup. Independent attempts; never retry or re-arm.
        context = _BackupContext(
            fd=fd,
            path=path,
            dst=dst,
            src=src,
            old_handler=old_handler,
            old_timer=old_timer,
            start=start,
        )
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        signal.setitimer(signal.ITIMER_REAL, 0)
        try:
            errors = _close_resources(context)
            errors.extend(_unlink_output(context.path))
        finally:
            # Drain our pending one-shot before restoring a default handler.
            _restore_alarm(mask, context)
        if errors:
            raise errors[0]


def main() -> None:
    """Run the backup from CLI arguments and report only an opaque failure flag."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="/data/spi.sqlite")
    p.add_argument("--private-pvc-directory", required=True)
    p.add_argument("--deadline-seconds", type=float, default=60)
    a = p.parse_args()
    try:
        backup(a.source, a.private_pvc_directory, deadline_seconds=a.deadline_seconds)
    except Exception:
        # Do not expose SQLite messages, paths, source data or credentials.
        print("BACKUP_FAILED: output invalid; delete private host file", file=sys.stderr)
        # Avoid interpreter shutdown re-flushing a broken/blocked stdout pipe.
        os._exit(1)


if __name__ == "__main__":
    main()
