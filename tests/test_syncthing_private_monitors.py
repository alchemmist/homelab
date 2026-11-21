"""Check the private Syncthing monitor migration against a temporary database."""

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "monitor_migration", ROOT / "ansible/files/migrate_syncthing_health_monitors.py"
)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)

MIGRATED_DB_MODE = 0o600


class SyncthingMonitorMigrationTests(unittest.TestCase):
    """Migrate one named monitor and leave every other stored row unchanged."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "kuma.db"
        connection = sqlite3.connect(self.database)
        connection.execute(
            "CREATE TABLE monitor (id INTEGER PRIMARY KEY, name TEXT, url TEXT, method TEXT, accepted_statuscodes_json TEXT, description TEXT, active INTEGER, interval INTEGER)"
        )
        connection.executemany(
            "INSERT INTO monitor VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    1,
                    "Syncthing sync-0",
                    "http://10.250.0.1:8384/",
                    "HEAD",
                    '["200-499"]',
                    "old",
                    1,
                    60,
                ),
                (2, "Other service", "https://example.com", "GET", '["200"]', "keep", 0, 120),
            ],
        )
        connection.commit()
        connection.close()
        self.plan = [{"name": "Syncthing sync-0", "url": "http://10.250.0.1:18444/healthz"}]

    def read_rows(self, database=None) -> list[tuple[int, str, str, str, str, str, int, int]]:
        connection = sqlite3.connect(database or self.database)
        rows = connection.execute("SELECT * FROM monitor ORDER BY id").fetchall()
        connection.close()
        return rows

    def test_check_is_read_only_and_creates_no_backup(self) -> None:
        """Report a pending change without writing the database or a backup."""
        before = self.read_rows()
        result = MIGRATION.migrate(self.database, self.plan, check=True)
        assert result["changed"]
        assert self.read_rows() == before
        assert not (self.database.parent / "backups").exists()

    def test_migration_preserves_unrelated_data_and_original_backup(self) -> None:
        """Update only the Syncthing URL and method and keep a private original backup."""
        before = self.read_rows()
        result = MIGRATION.migrate(self.database, self.plan)
        after = self.read_rows()
        assert self.read_rows(Path(result["backup"])) == before
        assert after[1] == before[1]
        assert after[0][6:] == before[0][6:]
        assert after[0][2] == self.plan[0]["url"]
        assert after[0][3] == "GET"
        assert json.loads(after[0][4]) == ["200"]
        assert Path(result["backup"]).stat().st_mode & 0o777 == MIGRATED_DB_MODE

    def test_repeat_and_unknown_monitor_are_noops(self) -> None:
        """Leave an already migrated database unchanged when an unknown monitor appears."""
        MIGRATION.migrate(self.database, self.plan)
        before = self.read_rows()
        plan = self.plan + [{"name": "Not configured", "url": "http://10.250.0.3:18444/healthz"}]
        assert not MIGRATION.migrate(self.database, plan)["changed"]
        assert self.read_rows() == before
        assert len(list((self.database.parent / "backups").glob("*.db"))) == 1


if __name__ == "__main__":
    unittest.main()
