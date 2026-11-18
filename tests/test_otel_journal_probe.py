"""Offline journal-probe contract using a fake process; journalctl is not executed."""

import importlib.util
import io
import subprocess
import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch

NORMAL_WAIT_TIMEOUT = 30
KILL_WAIT_TIMEOUT = 5

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "journal_probe", ROOT / "scripts/otel-journal-probe.py"
)
assert SPEC is not None
assert SPEC.loader is not None
JOURNAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(JOURNAL)


class Process:
    """In-memory journalctl stand-in with a preloaded stdout buffer."""

    def __init__(self, body: bytes, status: int = 0) -> None:
        """Buffer stdout and remember the exit status."""
        self.stdout = io.BytesIO(body)
        self.status = status
        self.terminated = False

    def terminate(self) -> None:
        """Record that the probe asked the process to stop."""
        self.terminated = True

    def wait(self, timeout: float) -> int:
        """Return the stored status immediately and remember the requested timeout."""
        self.wait_timeout = timeout
        return self.status


class JournalProbeTests(unittest.TestCase):
    """Check that collect() returns counts without persisting raw journal bodies."""

    def test_only_counts_are_returned(self) -> None:
        """Return counts only and keep the private journal body out of the result."""
        process = Process(b'{"MESSAGE":"private-body"}\n[]\ninvalid\n')
        expected_records = 3
        expected_invalid_records = 2
        with (
            patch.object(JOURNAL.subprocess, "Popen", return_value=process),
            patch.object(JOURNAL.os, "geteuid", return_value=0),
        ):
            result = JOURNAL.collect()
        assert result["records"] == expected_records
        assert result["invalidRecords"] == expected_invalid_records
        assert result["messageBytes"] == len("private-body")
        assert "private-body" not in str(result)
        assert not result["rawLogBodiesPersisted"]
        assert result["rootAccessVerified"]
        assert result["systemJournalReadSucceeded"]
        assert process.wait_timeout == NORMAL_WAIT_TIMEOUT

    def test_record_limit_is_not_reported_as_complete(self) -> None:
        """Stop at the record cap and do not report a complete journal read."""
        process = Process(b'{"MESSAGE":"one"}\n{"MESSAGE":"two"}\n')
        with (
            patch.object(JOURNAL.subprocess, "Popen", return_value=process),
            patch.object(JOURNAL, "MAX_RECORDS", 1),
        ):
            result = JOURNAL.collect()
        assert process.terminated
        assert result["truncated"]
        assert not result["systemJournalReadSucceeded"]

    def test_long_record_is_bounded_before_json_decoding(self) -> None:
        """Truncate an oversized record before JSON decoding."""
        process = Process(b'{"MESSAGE":"' + b"x" * 1024 + b'"}\n')
        byte_cap = 64
        expected_serialized_bytes = 65
        with (
            patch.object(JOURNAL.subprocess, "Popen", return_value=process),
            patch.object(JOURNAL, "MAX_BYTES", byte_cap),
        ):
            result = JOURNAL.collect()
        assert result["serializedBytes"] == expected_serialized_bytes
        assert result["truncated"]
        assert result["records"] == 0

    def test_failed_journalctl_is_not_a_verified_source(self) -> None:
        """Refuse to treat a failed journalctl status as a verified read."""
        process = Process(b"", 1)
        with patch.object(JOURNAL.subprocess, "Popen", return_value=process):
            assert not JOURNAL.collect()["systemJournalReadSucceeded"]


class TimedOutProcess(Process):
    """Process double whose first wait times out and whose kill is observable."""

    @override
    def __init__(self) -> None:
        super().__init__(b"")
        self.waits: list[float] = []
        self.killed = False

    @override
    def wait(self, timeout: float) -> int:
        """Record both bounded waits and time out only the first one."""
        self.waits.append(timeout)
        if len(self.waits) == 1:
            raise subprocess.TimeoutExpired(["journalctl"], timeout)
        return self.status

    def kill(self) -> None:
        """Record forced cleanup on the in-memory double, not an OS process."""
        self.killed = True


def test_wait_timeout_kills_and_reaps_without_verified_success() -> None:
    """Treat a timed-out journal read as unverified even if cleanup later exits zero."""
    process = TimedOutProcess()
    with patch.object(JOURNAL.subprocess, "Popen", return_value=process):
        result = JOURNAL.collect()
    assert process.killed
    assert process.waits == [NORMAL_WAIT_TIMEOUT, KILL_WAIT_TIMEOUT]
    assert process.stdout.closed
    assert not result["systemJournalReadSucceeded"]
    assert not result["rawLogBodiesPersisted"]
    assert not result["productionModified"]
