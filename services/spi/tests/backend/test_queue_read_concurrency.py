"""Queue telemetry must not contend for SQLite's one WAL writer."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from core import Store


class QueueReadConcurrencyTests(unittest.TestCase):
    def test_health_reads_during_open_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'queue.sqlite')
            with store.db() as writer:
                writer.execute('INSERT INTO dispatch VALUES(1,?,?,?)', ('reserved', 42, 1))
                self.assertEqual(store.health()['counts'], {})
                self.assertEqual(store.dispatch_status()['attempts'], 0)
                with store.read_db() as reader, self.assertRaisesRegex(sqlite3.OperationalError, 'readonly'):
                    reader.execute('DELETE FROM dispatch')
            self.assertEqual(store.dispatch_status()['attempts'], 1)

    def test_unowned_backlog_does_not_scan_owner_priority_per_job(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'queue.sqlite')
            with store.db() as c:
                for i in range(100):
                    store._enqueue(c, {'event_key': str(i), 'episode': str(i)}, i)
                queries = []
                c.set_trace_callback(queries.append)
                first, due = store._schedule(c, 101)
                self.assertEqual((first['id'], due), ('0', 0))
                self.assertFalse(any('AS durable_stage' in q for q in queries))
