"""Reconcile final cold SPI source to the verified preseed.

Compare every field, including large text as SHA-256.
"""

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

PG_TABLE_COUNT = 19
type _RECEIPT_ROWS = dict[tuple[object, ...], tuple[object, ...]]
type _Receipt = tuple[object, int, _RECEIPT_ROWS, object, set[tuple[object, ...]]]
HANDOFF_ADVISORY_LOCK = "select pg_advisory_xact_lock(1397770578)"
UPSERT_BATCH = 16
SPI_DATABASE = "spi_triage"
SPI_PG_HOST = "pg-common-rw.postgres.svc.cluster.local"
PG_SSL_MODE = "verify-full"


def _quoted(parts: Iterable[str]) -> "sql.SQL":
    """Join reviewed identifiers into one comma-separated SQL identifiers list."""
    return sql.SQL(",").join(map(sql.Identifier, parts))


def _verify_source_integrity(src: sqlite3.Connection) -> None:
    """Require an intact, foreign-key-clean SQLite source before any reads."""
    src.execute("BEGIN")
    if src.execute("pragma integrity_check").fetchall() != [("ok",)]:
        msg = "SQLite source failed its integrity check"
        raise RuntimeError(msg)
    if src.execute("pragma foreign_key_check").fetchone():
        msg = "SQLite source has dangling foreign keys"
        raise RuntimeError(msg)


def _sqlite_tables(src: sqlite3.Connection) -> "list[str]":
    """Read the reviewed rowid-ordered list of source table names."""
    return [
        str(r[0])
        for r in src.execute("select name from sqlite_master where type='table' order by rowid")
    ]


def _verify_table_sets(src: sqlite3.Connection, db: psycopg.Connection) -> "list[str]":
    """Verify the reviewed table count and its exact match with PostgreSQL."""
    tabs = _sqlite_tables(src)
    if len(tabs) != PG_TABLE_COUNT:
        msg = "Expected " + str(PG_TABLE_COUNT) + " reviewed tables, got " + str(len(tabs))
        raise RuntimeError(msg)
    if set(tabs) != {
        str(r[0]) for r in db.execute("select tablename from pg_tables where schemaname='public'")
    }:
        msg = "SQLite table set differs from the PostgreSQL preseed"
        raise RuntimeError(msg)
    return tabs


def _verify_table_meta(
    src: sqlite3.Connection, db: psycopg.Connection, name: str
) -> "tuple[list[str], list[str], list[str]]":
    """Verify one table's keys and ordered columns against the PostgreSQL preseed."""
    cols = src.execute("pragma table_info(" + name + ")").fetchall()
    col_names = [str(r[1]) for r in cols]
    col_types = [str(r[2]).upper() for r in cols]
    keys = [str(r[1]) for r in sorted(cols, key=lambda r: r[5]) if r[5]]
    if not keys:
        msg = "Table " + name + " has no primary key"
        raise RuntimeError(msg)
    expected_names = [
        str(r[0])
        for r in db.execute(
            "select column_name from information_schema.columns"
            " where table_schema='public' and table_name=%s order by ordinal_position",
            (name,),
        )
    ]
    if col_names != expected_names:
        msg = "Table " + name + " columns differ from the PostgreSQL preseed"
        raise RuntimeError(msg)
    return col_names, col_types, keys


def _pg_rowmap(
    db: psycopg.Connection,
    query: "sql.SQL",
    nkeys: int,
    cursor_name: str = "checked_rows",
) -> "dict[tuple[object, ...], tuple[object, ...]]":
    """Stream one table's keyed signature rows into a dict."""
    with db.cursor(name=cursor_name) as cursor:
        cursor.itersize = 500
        cursor.execute(query)
        return {tuple(r[:nkeys]): tuple(r[nkeys:]) for r in cursor}


def _row_signature(col_types: "list[str]", row: "tuple[object, ...]") -> "tuple[object, ...]":
    """Build one row's comparison signature, hashing large TEXT as SHA-256."""
    return tuple(
        hashlib.sha256(str(v).encode()).digest() if typ == "TEXT" and v is not None else v
        for typ, v in zip(col_types, row, strict=False)
    )


def _upsert(col_names: "list[str]", keys: "list[str]", name: str) -> "sql.SQL":
    """Compose the reviewed upsert for one table."""
    nonkeys = [n for n in col_names if n not in keys]
    action = (
        sql.SQL("DO UPDATE SET ")
        + sql.SQL(",").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(n), sql.Identifier(n)) for n in nonkeys
        )
        if nonkeys
        else sql.SQL("DO NOTHING")
    )
    return (
        sql.SQL("insert into {} ({}) values ({}) on conflict ({}) ").format(
            sql.Identifier(name),
            _quoted(col_names),
            sql.SQL(",").join(sql.Placeholder() for _ in col_names),
            _quoted(keys),
        )
        + action
    )


def _reconcile_table(
    src: sqlite3.Connection, db: psycopg.Connection, t: str
) -> "tuple[sql.SQL, int, _RECEIPT_ROWS, sql.SQL, set[tuple[object, ...]], int]":
    """Reconcile one reviewed table, returning its receipt parts and upsert count."""
    col_names, col_types, keys = _verify_table_meta(src, db, t)
    pgsig = sql.SQL(",").join(
        sql.SQL("sha256(convert_to({},'UTF8'))").format(sql.Identifier(n))
        if typ == "TEXT"
        else sql.Identifier(n)
        for n, typ in zip(col_names, col_types, strict=False)
    )
    query = sql.SQL("select {},{} from {}").format(_quoted(keys), pgsig, sql.Identifier(t))
    old = _pg_rowmap(db, query, len(keys))
    expected: dict[tuple[object, ...], tuple[object, ...]] = {}
    pending = []
    up = _upsert(col_names, keys, t)
    changes = 0
    for row in src.execute("select * from " + t):
        key = tuple(row[col_names.index(n)] for n in keys)
        sig = _row_signature(col_types, tuple(row))
        expected[key] = sig
        if old.get(key) != sig:
            pending.append(row)
            changes += 1
            if len(pending) >= UPSERT_BATCH:
                with db.cursor() as writer:
                    writer.executemany(up, pending)
                pending = []
    if pending:
        with db.cursor() as writer:
            writer.executemany(up, pending)
    extras = old.keys() - expected.keys()
    delete = sql.SQL("delete from {} where ").format(sql.Identifier(t)) + sql.SQL(" AND ").join(
        sql.SQL("{}=%s").format(sql.Identifier(n)) for n in keys
    )
    return query, len(keys), expected, delete, extras, changes


def _delete_extras(
    db: psycopg.Connection,
    todo: list[_Receipt],
) -> int:
    """Delete PostgreSQL rows absent from the source, newest table first."""
    deletes = 0
    for _, _, _, q, extra in reversed(todo):
        for k in extra:
            db.execute(q, k)
            deletes += 1
    return deletes


def _final_verify(
    db: psycopg.Connection,
    todo: list[_Receipt],
) -> None:
    """Re-read every reconciled table and require the exact typed receipt."""
    for q, n, expected, _, _ in todo:
        actual = _pg_rowmap(db, q, n, cursor_name="final_verify")
        if actual != expected:
            msg = "Final typed receipt differs"
            raise RuntimeError(msg)


def reconcile(src: sqlite3.Connection, db: psycopg.Connection, *, _verify_only: bool) -> None:
    """Reconcile the final cold source into the locked PostgreSQL preseed."""
    _verify_source_integrity(src)
    tabs = _verify_table_sets(src, db)
    db.execute(HANDOFF_ADVISORY_LOCK)
    # Handoff holds a different lock during the bulk import; the final
    # activation is a separate short transaction.
    changes = deletes = total = 0
    todo: list[_Receipt] = []
    for t in tabs:
        query, nkeys, expected, delete, extras, table_changes = _reconcile_table(src, db, t)
        todo.append((query, nkeys, expected, delete, extras))
        changes += table_changes
        total += len(expected)
    deletes = _delete_extras(db, todo)
    _final_verify(db, todo)
    for t in ("llm_admission", "queue_operator_actions"):
        db.execute(
            sql.SQL(
                "SELECT setval(pg_get_serial_sequence(%s,'id'),"
                "coalesce(max(id),1),count(*)>0) FROM {}"
            ).format(sql.Identifier(t)),
            (t,),
        )
    print(
        "verified tables",
        len(tabs),
        "rows",
        total,
        "upserts",
        changes,
        "deletes",
        deletes,
        flush=True,
    )


if __name__ == "__main__":
    _mode = sys.argv[1]
    if _mode not in ("seed", "cold"):
        msg = "Mode must be one of the reviewed rehearsal phases"
        raise RuntimeError(msg)
    url = os.environ["SPI_POSTGRES_URL"]
    info = conninfo_to_dict(url)
    if info["dbname"] != SPI_DATABASE:
        msg = "Connection must target the reviewed SPI database"
        raise RuntimeError(msg)
    if info["host"] != SPI_PG_HOST:
        msg = "Connection must target the reviewed in-cluster PostgreSQL host"
        raise RuntimeError(msg)
    if info["sslmode"] != PG_SSL_MODE:
        msg = "Connection must verify PostgreSQL TLS"
        raise RuntimeError(msg)
    with tempfile.TemporaryDirectory() as tmp, psycopg.connect(url) as db:
        if db.execute("select live from handoff.mode").fetchone() != (False,):
            msg = "Handoff mode must not be live during finalize"
            raise RuntimeError(msg)
        if _mode == "seed":
            if db.execute("select from pg_tables where schemaname='public'").fetchone():
                msg = "Seed rehearsal requires an empty public schema"
                raise RuntimeError(msg)
            db.execute(Path(__file__).with_name("schema.sql").read_text())
            source_path = Path("/src/.spi-pg-rehearsal.sqlite")
        else:
            source_path = Path(tmp) / "spi.sqlite"
            for suffix in ("", "-wal", "-journal"):
                f = Path("/src") / (source_path.name + suffix)
                if f.exists():
                    shutil.copyfile(f, str(source_path) + suffix)
        with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as src:
            reconcile(src, db, _verify_only=_mode == "cold")
