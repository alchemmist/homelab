import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('journal_probe', ROOT / 'scripts/otel-journal-probe.py')
JOURNAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(JOURNAL)


class Process:
    def __init__(self, body, status=0):
        self.stdout = io.BytesIO(body)
        self.status = status
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        return self.status


class JournalProbeTests(unittest.TestCase):
    def test_only_counts_are_returned(self):
        process = Process(b'{"MESSAGE":"private-body"}\n[]\ninvalid\n')
        with patch.object(JOURNAL.subprocess, 'Popen', return_value=process), patch.object(JOURNAL.os, 'geteuid', return_value=0):
            result = JOURNAL.collect()
        self.assertEqual(result['records'], 3)
        self.assertEqual(result['invalidRecords'], 2)
        self.assertEqual(result['messageBytes'], len('private-body'))
        self.assertNotIn('private-body', str(result))
        self.assertFalse(result['rawLogBodiesPersisted'])
        self.assertTrue(result['rootAccessVerified'])
        self.assertTrue(result['systemJournalReadSucceeded'])

    def test_record_limit_is_not_reported_as_complete(self):
        process = Process(b'{"MESSAGE":"one"}\n{"MESSAGE":"two"}\n')
        with patch.object(JOURNAL.subprocess, 'Popen', return_value=process), patch.object(JOURNAL, 'MAX_RECORDS', 1):
            result = JOURNAL.collect()
        self.assertTrue(process.terminated)
        self.assertTrue(result['truncated'])
        self.assertFalse(result['systemJournalReadSucceeded'])

    def test_long_record_is_bounded_before_json_decoding(self):
        process = Process(b'{"MESSAGE":"' + b'x' * 1024 + b'"}\n')
        with patch.object(JOURNAL.subprocess, 'Popen', return_value=process), patch.object(JOURNAL, 'MAX_BYTES', 64):
            result = JOURNAL.collect()
        self.assertEqual(result['serializedBytes'], 65)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['records'], 0)

    def test_failed_journalctl_is_not_a_verified_source(self):
        process = Process(b'', 1)
        with patch.object(JOURNAL.subprocess, 'Popen', return_value=process):
            self.assertFalse(JOURNAL.collect()['systemJournalReadSucceeded'])
