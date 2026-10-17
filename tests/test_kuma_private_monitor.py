from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ansible/roles/uptime_kuma_private_monitoring/files/configure_monitor.py"
)
SPEC = importlib.util.spec_from_file_location("configure_monitor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class KumaPrivateMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "kuma.db"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript(
                "CREATE TABLE monitor (id INTEGER PRIMARY KEY, name TEXT, type TEXT, "
                "url TEXT, keyword TEXT, method TEXT, accepted_statuscodes_json TEXT, "
                "ignore_tls INTEGER, invert_keyword INTEGER, upside_down INTEGER, "
                "maxredirects INTEGER, interval INTEGER, notification TEXT);"
                "CREATE TABLE heartbeat (monitor_id INTEGER, status INTEGER);"
                "CREATE TABLE monitor_group (monitor_id INTEGER, group_id INTEGER);"
            )
            db.executemany(
                "INSERT INTO monitor VALUES (?, ?, 'http', ?, '', 'GET', "
                "'[\"200-299\"]', 0, 0, 0, 10, 60, 'preserved')",
                [(7, "Control plane", f"https://{MODULE.HOSTNAME}"),
                 (8, "Other service", "https://status.example.org")],
            )
            db.execute("INSERT INTO heartbeat VALUES (7, 0)")
            db.execute("INSERT INTO monitor_group VALUES (7, 4)")

    def snapshot(self, path=None):
        with closing(sqlite3.connect(path or self.path)) as db, db:
            return {
                table: db.execute(f"SELECT * FROM {table}").fetchall()
                for table in ("monitor", "heartbeat", "monitor_group")
            }

    def test_migration_preserves_history_groups_identity_and_unrelated_fields(self):
        before = self.snapshot()
        result = MODULE.configure(self.path)
        self.assertEqual(result["monitor_id"], 7)
        self.assertTrue(result["changed"])
        self.assertEqual(self.snapshot(result["backup"]), before)
        after = self.snapshot()
        self.assertEqual(after["heartbeat"], before["heartbeat"])
        self.assertEqual(after["monitor_group"], before["monitor_group"])
        self.assertEqual(after["monitor"][1], before["monitor"][1])
        self.assertEqual(after["monitor"][0][:2], before["monitor"][0][:2])
        self.assertEqual(after["monitor"][0][-2:], before["monitor"][0][-2:])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM monitor WHERE id = 7").fetchone()
            self.assertEqual({key: row[key] for key in MODULE.DESIRED}, MODULE.DESIRED)
        backup = Path(result["backup"])
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)

    def test_check_is_read_only_and_apply_is_idempotent(self):
        before = self.path.read_bytes()
        self.assertEqual(MODULE.configure(self.path, check=True),
                         {"changed": True, "monitor_id": 7})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.path.parent / "backups").exists())
        MODULE.configure(self.path)
        expected = {"changed": False, "monitor_id": 7}
        self.assertEqual(MODULE.configure(self.path), expected)
        self.assertEqual(MODULE.configure(self.path, check=True), expected)
        self.assertEqual(len(list((self.path.parent / "backups").iterdir())), 1)

    def test_ambiguous_monitor_is_refused_without_writes(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE monitor SET url = ? WHERE id = 8",
                       (f"https://{MODULE.HOSTNAME}/ping",))
        before = self.path.read_bytes()
        for check in (True, False):
            with self.assertRaisesRegex(ValueError, "found 2"):
                MODULE.configure(self.path, check=check)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.path.parent / "backups").exists())

    def test_missing_monitor_and_database_are_not_created(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM monitor WHERE id = 7")
        with self.assertRaisesRegex(ValueError, "found 0"):
            MODULE.configure(self.path)
        missing = self.path.parent / "missing.db"
        for check in (True, False):
            with self.assertRaises(sqlite3.OperationalError):
                MODULE.configure(missing, check=check)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
