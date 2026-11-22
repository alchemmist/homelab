"""Offline hash regressions; isolated Linux fast runs generate their own pressure fixture."""

import importlib.util
import os
import pwd
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import pytest

from ci.quality.common import command

spec = importlib.util.spec_from_file_location(
    "retry", Path(__file__).resolve().parents[1] / "scripts/n8n/spi_operator_retry.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SHA256_HEX_LENGTH = 64


def _verify_read_only_sort(database: Path) -> None:
    """Require the old sort to run out of disk, not fail for a different reason."""
    with closing(
        sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, isolation_level=None)
    ) as c:
        c.row_factory = sqlite3.Row
        assert c.execute("PRAGMA temp_store").fetchone()[0] == 0
        c.execute("BEGIN IMMEDIATE")
        try:
            for _ in c.execute("SELECT * FROM payload ORDER BY 1,2"):
                pass
        except sqlite3.OperationalError as error:
            if (
                error.sqlite_errorcode != sqlite3.SQLITE_FULL
                or "database or disk is full" not in str(error)
            ):
                raise
        else:
            message = "The full-row sort did not exhaust the temporary filesystem"
            raise AssertionError(message)
        first = m.table_hashes(c)["payload"]
        assert len(first) == SHA256_HEX_LENGTH
        assert m.table_hashes(c)["payload"] == first
        c.rollback()


def _linux_sort_reproduction() -> None:
    """Run only this regression with a real 1 MiB SQLite temp filesystem, not the whole suite."""
    if not sys.platform.startswith("linux") or os.getuid() == 0:
        message = "The synthetic sort fixture requires an unprivileged Linux test runner"
        raise RuntimeError(message)
    with tempfile.TemporaryDirectory(prefix="spi-sort-") as directory:
        database = Path(directory) / "synthetic.db"
        with closing(sqlite3.connect(database)) as db:
            db.execute("CREATE TABLE payload(sort_key INTEGER, body TEXT)")
            db.executemany(
                "INSERT INTO payload VALUES(?, ?)",
                ((i, "x" * 4096) for i in range(14000, 0, -1)),
            )
            db.commit()
        database.chmod(0o400)
        # /dev/shm is covered ONLY in this private child mount namespace. No
        # repository code is executed as root. runuser drops privileges before
        # Python; env -i does not pass through credentials or fixture selectors.
        command(
            [
                "/usr/bin/sudo",
                "-n",
                "/usr/bin/unshare",
                "--net",
                "--mount",
                "--propagation",
                "private",
                "--",
                "/bin/sh",
                "-ec",
                "/usr/bin/mount -t tmpfs -o size=1m,nodev,nosuid,noexec,mode=1777 "
                'tmpfs /dev/shm && exec "$@"',
                "sort-fixture",
                "/usr/sbin/runuser",
                "-u",
                pwd.getpwuid(os.getuid()).pw_name,
                "--",
                "/usr/bin/env",
                "-i",
                "HOME=" + directory,
                "KUBECONFIG=/dev/null",
                "SQLITE_TMPDIR=/dev/shm",
                "PYTHONDONTWRITEBYTECODE=1",
                "/usr/bin/timeout",
                "--kill-after=3s",
                "45s",
                sys.executable,
                "-c",
                "import sys; from pathlib import Path; "
                "from tests.test_spi_operator_hash import _verify_read_only_sort; "
                "_verify_read_only_sort(Path(sys.argv[1]))",
                str(database),
            ],
            timeout=60,
        )


class HashTests(unittest.TestCase):
    """In-memory checks for transaction-local table hashes."""

    def connection(self) -> sqlite3.Connection:
        c = sqlite3.connect(":memory:", isolation_level=None)
        c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        return c

    def test_orders_and_identifiers(self) -> None:
        """Keep hashes stable across rollback and sensitive to row changes."""
        for ddl in (
            'CREATE TABLE "a""b"("rowid" TEXT, "oid" TEXT, k TEXT, v BLOB)',
            'CREATE TABLE "a""b"(k TEXT, v BLOB, PRIMARY KEY(k DESC)) WITHOUT ROWID',
        ):
            with self.subTest(ddl=ddl):
                c = self.connection()
                c.execute(ddl)
                n = len(c.execute('SELECT * FROM "a""b"').description)
                for key in ("z", "a", "m"):
                    c.execute(
                        'INSERT INTO "a""b" VALUES(' + ",".join("?" for _ in range(n)) + ")",
                        ([key] * (n - 1) + [b"payload"]),
                    )
                c.execute("BEGIN IMMEDIATE")
                before = m.table_hashes(c)
                assert before == m.table_hashes(c)
                c.execute('UPDATE "a""b" SET v=?', (b"changed",))
                assert before != m.table_hashes(c)
                c.rollback()
                assert before == m.table_hashes(c)

    def test_shadowed_aliases_refused(self) -> None:
        """Refuse tables whose names shadow SQLite rowid aliases."""
        c = self.connection()
        c.execute("CREATE TABLE t(rowid, _rowid_, oid, value)")
        with pytest.raises(ValueError, match="shadowed"):
            m.table_hashes(c)

    def test_virtual_refused(self) -> None:
        """Refuse virtual tables that have no physical btree order."""
        c = self.connection()
        c.execute("CREATE VIRTUAL TABLE t USING fts5(value)")
        with pytest.raises(ValueError, match="unsupported table kind"):
            m.table_hashes(c)

    def test_physical_order_is_not_external_canonical(self) -> None:
        """Show that insertion order changes the external hash."""
        hashes = []
        for values in (("a", "b"), ("b", "a")):
            c = self.connection()
            c.execute("CREATE TABLE t(value)")
            c.executemany("INSERT INTO t VALUES(?)", [(v,) for v in values])
            hashes.append(m.table_hashes(c))
        assert hashes[0] != hashes[1]

    @unittest.skipUnless(
        os.environ.get("SPI_SORT_FIXTURE") or os.environ.get("QUALITY_SYNTHETIC_SPI_SORT") == "1",
        "requires host fixture and tiny container tmpfs or the isolated Linux fast runner",
    )
    def test_disk_full_sort_reproduction(self) -> None:
        """Prove the old query hits SQLITE_FULL; hash the same real rows twice without sorting."""
        if os.environ.get("QUALITY_SYNTHETIC_SPI_SORT") == "1":
            _linux_sort_reproduction()
            return
        _verify_read_only_sort(Path(os.environ["SPI_SORT_FIXTURE"]))


if __name__ == "__main__":
    unittest.main()
