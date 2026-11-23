"""Tests for the private Uptime Kuma monitoring configuration script."""

import importlib.util
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import cast, override

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ansible/roles/uptime_kuma_private_monitoring/files/configure_monitor.py"
)
SPEC = importlib.util.spec_from_file_location("configure_monitor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class KumaPrivateMonitorTests(unittest.TestCase):
    """Validate Uptime Kuma's private monitoring database."""

    @override
    def setUp(self) -> None:
        """Seed a copied kuma.db with one control-plane monitor and history."""
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
                [
                    (7, "Control plane", f"https://{MODULE.HOSTNAME}"),
                    (8, "Other service", "https://status.example.org"),
                ],
            )
            db.execute("INSERT INTO heartbeat VALUES (7, 0)")
            db.execute("INSERT INTO monitor_group VALUES (7, 4)")

    def snapshot(self, path: Path | None = None) -> dict[str, list[sqlite3.Row]]:
        """Materialise every surviving row grouped per table."""
        with closing(sqlite3.connect(path or self.path)) as db, db:
            return cast(
                "dict[str, list[sqlite3.Row]]",
                {
                    table: db.execute(f"SELECT * FROM {table}").fetchall()
                    for table in ("monitor", "heartbeat", "monitor_group")
                },
            )

    def test_migration_preserves_history_groups_identity_and_unrelated_fields(
        self,
    ) -> None:
        """Rewrite identity while preserving history, groups, and layout."""
        before = self.snapshot()
        result = MODULE.configure(self.path)
        assert result["monitor_id"] == 7
        assert result["changed"]
        assert self.snapshot(result["backup"]) == before
        after = self.snapshot()
        assert after["heartbeat"] == before["heartbeat"]
        assert after["monitor_group"] == before["monitor_group"]
        assert after["monitor"][1] == before["monitor"][1]
        assert after["monitor"][0][:2] == before["monitor"][0][:2]
        assert after["monitor"][0][-2:] == before["monitor"][0][-2:]
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM monitor WHERE id = 7").fetchone()
            assert row is not None
            assert {key: row[key] for key in MODULE.DESIRED} == MODULE.DESIRED
        backup = Path(result["backup"])
        assert backup.stat().st_mode & 511 == 384
        assert backup.parent.stat().st_mode & 511 == 448

    def test_check_is_read_only_and_apply_is_idempotent(self) -> None:
        """Keep check mode read-only and apply idempotently once."""
        before = self.path.read_bytes()
        assert MODULE.configure(self.path, check=True) == {"changed": True, "monitor_id": 7}
        assert self.path.read_bytes() == before
        assert not (self.path.parent / "backups").exists()
        MODULE.configure(self.path)
        expected = {"changed": False, "monitor_id": 7}
        assert MODULE.configure(self.path) == expected
        assert MODULE.configure(self.path, check=True) == expected
        assert len(list((self.path.parent / "backups").iterdir())) == 1

    def test_ambiguous_monitor_is_refused_without_writes(self) -> None:
        """Refuse ambiguous matches without leaving any database writes."""
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "UPDATE monitor SET url = ? WHERE id = 8",
                (f"https://{MODULE.HOSTNAME}/ping",),
            )
        before = self.path.read_bytes()
        for check in (True, False):
            with pytest.raises(ValueError, match="found 2"):
                MODULE.configure(self.path, check=check)
        assert self.path.read_bytes() == before
        assert not (self.path.parent / "backups").exists()

    def test_missing_monitor_and_database_are_not_created(self) -> None:
        """Fail closed for absent monitors and never create a database."""
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM monitor WHERE id = 7")
        with pytest.raises(ValueError, match="found 0"):
            MODULE.configure(self.path)
        missing = self.path.parent / "missing.db"
        for check in (True, False):
            with pytest.raises(sqlite3.OperationalError):
                MODULE.configure(missing, check=check)
        assert not missing.exists()


if __name__ == "__main__":
    unittest.main()
