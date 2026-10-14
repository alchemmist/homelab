import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'monitor_migration', ROOT / 'ansible/files/migrate_syncthing_health_monitors.py'
)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class SyncthingMonitorMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / 'kuma.db'
        connection = sqlite3.connect(self.database)
        connection.execute(
            'CREATE TABLE monitor (id INTEGER PRIMARY KEY, name TEXT, url TEXT, method TEXT, accepted_statuscodes_json TEXT, description TEXT, active INTEGER, interval INTEGER)'
        )
        connection.executemany(
            'INSERT INTO monitor VALUES (?,?,?,?,?,?,?,?)',
            [
                (1, 'Syncthing sync-0', 'http://10.250.0.1:8384/', 'HEAD', '["200-499"]', 'old', 1, 60),
                (2, 'Other service', 'https://example.com', 'GET', '["200"]', 'keep', 0, 120),
            ],
        )
        connection.commit()
        connection.close()
        self.plan = [{'name': 'Syncthing sync-0', 'url': 'http://10.250.0.1:18444/healthz'}]

    def read_rows(self, database=None):
        connection = sqlite3.connect(database or self.database)
        rows = connection.execute('SELECT * FROM monitor ORDER BY id').fetchall()
        connection.close()
        return rows

    def test_check_is_read_only_and_creates_no_backup(self):
        before = self.read_rows()
        result = MIGRATION.migrate(self.database, self.plan, check=True)
        self.assertTrue(result['changed'])
        self.assertEqual(self.read_rows(), before)
        self.assertFalse((self.database.parent / 'backups').exists())

    def test_migration_preserves_unrelated_data_and_original_backup(self):
        before = self.read_rows()
        result = MIGRATION.migrate(self.database, self.plan)
        after = self.read_rows()
        self.assertEqual(self.read_rows(Path(result['backup'])), before)
        self.assertEqual(after[1], before[1])
        self.assertEqual(after[0][6:], before[0][6:])
        self.assertEqual(after[0][2], self.plan[0]['url'])
        self.assertEqual(after[0][3], 'GET')
        self.assertEqual(json.loads(after[0][4]), ['200'])
        self.assertEqual(Path(result['backup']).stat().st_mode & 0o777, 0o600)

    def test_repeat_and_unknown_monitor_are_noops(self):
        MIGRATION.migrate(self.database, self.plan)
        before = self.read_rows()
        plan = self.plan + [{'name': 'Not configured', 'url': 'http://10.250.0.3:18444/healthz'}]
        self.assertFalse(MIGRATION.migrate(self.database, plan)['changed'])
        self.assertEqual(self.read_rows(), before)
        self.assertEqual(len(list((self.database.parent / 'backups').glob('*.db'))), 1)


if __name__ == '__main__':
    unittest.main()
