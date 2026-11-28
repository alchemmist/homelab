"""Import canonical SPI data into an empty PG database. Never use while PG worker is live."""

import collections
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

if TYPE_CHECKING:
    from collections.abc import Iterable

PG_TABLE_COUNT = 19
SPI_DATABASE = "spi_triage"
SPI_PG_HOST = "pg-common-rw.postgres.svc.cluster.local"
PG_SSL_MODE = "verify-full"
COPY_BATCH = 8


def receipt(rows: "Iterable[Iterable[object]]") -> "collections.Counter[bytes]":
    """Fingerprint every row as a counter of SHA-256 digests."""
    return collections.Counter(
        hashlib.sha256(
            json.dumps(
                tuple(row), ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode()
        ).digest()
        for row in rows
    )


def _verify_source_clean(src: sqlite3.Connection) -> None:
    """Require an intact, foreign-key-clean SQLite source before the import."""
    src.execute("BEGIN")
    if src.execute("pragma integrity_check").fetchall() != [("ok",)]:
        msg = "SQLite source failed its integrity check"
        raise RuntimeError(msg)
    if src.execute("pragma foreign_key_check").fetchone():
        msg = "SQLite source has dangling foreign keys"
        raise RuntimeError(msg)


def _verify_schema(src: sqlite3.Connection, db: psycopg.Connection) -> "list[str]":
    """Apply the reviewed schema and verify the exact reviewed table set."""
    if db.execute("select from pg_tables where schemaname='public'").fetchone():
        msg = "Target database must be empty before the import"
        raise RuntimeError(msg)
    db.execute(Path(__file__).with_name("schema.sql").read_text())
    tabs = [
        str(r[0])
        for r in src.execute("select name from sqlite_master where type='table' order by rowid")
    ]
    if len(tabs) != PG_TABLE_COUNT:
        msg = "Expected " + str(PG_TABLE_COUNT) + " reviewed tables, got " + str(len(tabs))
        raise RuntimeError(msg)
    if set(tabs) != {
        str(r[0]) for r in db.execute("select tablename from pg_tables where schemaname='public'")
    }:
        msg = "SQLite table set differs from the applied schema"
        raise RuntimeError(msg)
    return tabs


def _verify_columns(src: sqlite3.Connection, db: psycopg.Connection, t: str) -> "list[str]":
    """Verify one table's column list matches the applied PostgreSQL schema."""
    cols = [str(r[1]) for r in src.execute("pragma table_info(" + t + ")")]
    if cols != [
        str(r[0])
        for r in db.execute(
            "select column_name from information_schema.columns"
            " where table_schema='public' and table_name=%s order by ordinal_position",
            (t,),
        )
    ]:
        msg = "Table " + t + " columns differ from the applied schema"
        raise RuntimeError(msg)
    return cols


def _copy_table(src: sqlite3.Connection, db: psycopg.Connection, t: str) -> int:
    """Copy one reviewed table and verify its row-receipt and count."""
    table = sql.Identifier(t)
    cols = _verify_columns(src, db, t)
    columns = sql.SQL(",").join(map(sql.Identifier, cols))
    expected: collections.Counter[bytes] = collections.Counter()
    source_rows = src.execute("select * from " + t)
    while batch := source_rows.fetchmany(COPY_BATCH):
        with db.cursor().copy(sql.SQL("COPY {} ({}) FROM STDIN").format(table, columns)) as cp:
            for row in batch:
                cp.write_row(row)
        expected.update(receipt(batch))
    with db.cursor(name="verify_rows") as c:
        c.itersize = 2 * COPY_BATCH
        c.execute(sql.SQL("SELECT {} FROM {}").format(columns, table))
        if receipt(c) != expected:
            msg = t + " receipt mismatch"
            raise RuntimeError(msg)
    count = sum(expected.values())
    print(t, count, flush=True)
    return count


def transfer(src: sqlite3.Connection, db: psycopg.Connection) -> int:
    """Import every reviewed table and return the verified row total."""
    _verify_source_clean(src)
    tabs = _verify_schema(src, db)
    total = 0
    for t in tabs:
        total += _copy_table(src, db, t)
    for t in ("llm_admission", "queue_operator_actions"):
        db.execute(
            sql.SQL(
                "SELECT setval(pg_get_serial_sequence(%s,'id'),"
                "coalesce(max(id),1),count(*)>0) FROM {}"
            ).format(sql.Identifier(t)),
            (t,),
        )
    return total


def _require_connection_target(params: dict[str, str]) -> None:
    """Require the reviewed SPI database host and TLS mode before touching it."""
    if params["host"] != SPI_PG_HOST:
        msg = "Connection must target the reviewed in-cluster PostgreSQL host"
        raise RuntimeError(msg)
    if params["dbname"] != SPI_DATABASE:
        msg = "Connection must target the reviewed SPI database"
        raise RuntimeError(msg)
    if params["sslmode"] != PG_SSL_MODE:
        msg = "Connection must verify PostgreSQL TLS"
        raise RuntimeError(msg)


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode not in ("trial", "cold"):
        msg = "Mode must be one of the reviewed rehearsal phases"
        raise RuntimeError(msg)
    url = os.environ["SPI_POSTGRES_URL"]
    params = conninfo_to_dict(url)
    _require_connection_target(params)
    src_path = Path("/src/.spi-pg-rehearsal.sqlite" if mode == "trial" else "/src/spi.sqlite")
    with tempfile.TemporaryDirectory() as tmp:
        if mode == "cold":
            for suffix in ("", "-wal", "-journal"):
                f = Path(str(src_path) + suffix)
                if f.exists():
                    shutil.copyfile(f, Path(tmp) / f.name)
            src_path = Path(tmp) / src_path.name
        with (
            sqlite3.connect(src_path.as_uri() + "?mode=ro", uri=True) as src,
            psycopg.connect(url) as dst,
        ):
            total = transfer(src, dst)
            if mode == "trial":
                dst.rollback()
            print("verified total", total, mode, flush=True)
