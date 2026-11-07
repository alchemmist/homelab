import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'charts/monitoring-k3s/files/n8n-activity-exporter.py'
spec = importlib.util.spec_from_file_location('observer', PATH)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class ActivityTest(unittest.TestCase):
    def test_count_by_start_not_completion_and_no_duplicates(self):
        now = observer.timestamp('2026-11-07T10:00:00Z')
        rows = [
            {'id': '1', 'startedAt': '2026-11-07T09:58:00Z', 'status': 'success'},
            {'id': '1', 'startedAt': '2026-11-07T09:58:00Z', 'status': 'success'},
            {'id': '2', 'startedAt': '2026-11-07T09:30:00Z', 'status': 'error'},
            {'id': '3', 'startedAt': '2026-11-07T08:00:00Z', 'stoppedAt': '2026-11-07T09:59:00Z', 'status': 'success'},
            {'id': '4', 'startedAt': '2026-11-07T09:59:00Z', 'status': 'waiting'},
        ]
        counts = observer.summarize(rows, now)
        self.assertEqual(counts['success', 300], 1)
        self.assertEqual(counts['success', 3600], 1)
        self.assertEqual(counts['error', 300], 0)
        self.assertEqual(counts['error', 3600], 1)
        self.assertEqual(counts['running', 300], 0)
        self.assertEqual(counts['waiting', 300], 1)

    def test_running_is_fetched_separately_and_old_runs_still_count(self):
        old = observer.get_page
        observer.get_page = lambda cursor=None, status=None: {'data': [{'id': 'old', 'startedAt': '2020-01-01T00:00:00Z', 'status': 'running'}] if status else [], 'nextCursor': None}
        try:
            self.assertEqual(observer.collect()['running', 0], 1)
        finally:
            observer.get_page = old

    def test_scan_budget_does_not_publish_partial_counts(self):
        old = observer.get_page
        observer.get_page = lambda *args: {'data': [], 'nextCursor': 'more'}
        try:
            with self.assertRaises(RuntimeError):
                observer.collect()
        finally:
            observer.get_page = old

    def test_read_only_and_no_execution_payloads(self):
        source = PATH.read_text()
        self.assertIn("'includeData': 'false'", source)
        self.assertNotIn('method=', source)
        self.assertNotIn('print(', source)
