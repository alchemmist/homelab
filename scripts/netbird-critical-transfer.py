"""NetBird v0.83.2 offline transfer into pg-critical databases.

Never reuse against a live database. Caller must stop all target writers.
Dex keeps its native migration ledger.
"""

import collections
import datetime as dt
import decimal
import json
import pathlib
import re
import shutil
import sqlite3
import sys
import tempfile
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Iterable

import psycopg
from psycopg.types.json import Json, Jsonb

NAMES = {
    "idp": "netbird_idp",
    "events": "netbird_activity",
    "store": "netbird",
    "access_logs": "netbird_access",
}
LEGACY = {
    "peer_status_last_seen": "timestamptz",
    "peer_status_session_started_at": "bigint",
    "peer_status_connected": "boolean",
}
DEX_MIGRATIONS_PG = 22
DEX_MIGRATIONS_SQLITE = 23


def q(n: str) -> str:
    """Quote one trusted identifier for embedding into the reviewed SQL."""
    if not re.fullmatch("[a-zA-Z_][a-zA-Z_0-9]*", n):
        msg = "Refusing to quote a non-identifier table or column name"
        raise RuntimeError(msg)
    return '"' + n + '"'


def _convert_kind(v: object, k: str) -> object:
    """Normalize one non-null SQLite value to its reviewed pg domain."""
    if k == "bool":
        if v not in (True, False, 0, 1):
            msg = "unexpected boolean"
            raise ValueError(msg)
        return bool(v)
    if k == "timestamptz":
        stamp = dt.datetime.fromisoformat(v) if isinstance(v, str) else cast("dt.datetime", v)
        return (stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.UTC)).astimezone(dt.UTC)
    if k == "bytea":
        return v.encode() if isinstance(v, str) else bytes(cast("Iterable[int]", v))
    if k in ("int4", "int8"):
        return int(v) if isinstance(v, str) else cast("int", v)
    if k == "numeric":
        return decimal.Decimal(str(v))
    return v


def convert(v: object, k: str) -> object:
    """Convert one SQLite cell into its reviewed PostgreSQL representation."""
    if v is None:
        return None
    return _convert_kind(v, k)


def _verify_sqlite(src: sqlite3.Connection) -> None:
    """Refuse any source database that fails SQLite self checks."""
    if src.execute("pragma integrity_check").fetchall() != [("ok",)]:
        msg = "SQLite integrity_check failed on the source database"
        raise RuntimeError(msg)
    if src.execute("pragma foreign_key_check").fetchone():
        msg = "SQLite foreign_key_check reported violations on the source database"
        raise RuntimeError(msg)


def _verify_pg_ready(name: str, src: sqlite3.Connection, db: psycopg.Connection) -> set[str]:
    """Require identical public-table sets and the reviewed Dex ledger."""
    st = {
        r[0]
        for r in src.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
        )
    }
    pt = {r[0] for r in db.execute("select tablename from pg_tables where schemaname='public'")}
    if st != pt:
        msg = "Source and target table sets differ: " + name
        raise RuntimeError(msg)
    if name == "idp":
        pg_count = db.execute("select count(*) from migrations").fetchone()[0]
        if pg_count != DEX_MIGRATIONS_PG:
            msg = "Dex pg migration ledger must keep its reviewed count"
            raise RuntimeError(msg)
        sqlite_count = src.execute("select count(*) from migrations").fetchone()[0]
        if sqlite_count != DEX_MIGRATIONS_SQLITE:
            msg = "Source Dex migration ledger must keep its reviewed count"
            raise RuntimeError(msg)
    tables = set(st)
    if name == "idp":
        tables.remove("migrations")
    if name == "store":
        for column, typ in LEGACY.items():
            db.execute("ALTER TABLE peers ADD COLUMN IF NOT EXISTS " + q(column) + " " + typ)
    return tables


def _copy_table(name: str, t: str, src: sqlite3.Connection, db: psycopg.Connection) -> int:
    """Copy one reviewed table and verify the transferred values."""
    cols = list(
        db.execute(
            "select column_name,udt_name from information_schema.columns "
            "where table_schema='public' and table_name=%s order by ordinal_position",
            (t,),
        )
    )
    names = [n for n, _ in cols]
    if set(names) != {r[1] for r in src.execute("pragma table_info(" + q(t) + ")")}:
        msg = "Column mismatch: " + name + "/" + t
        raise RuntimeError(msg)
    colsql = ",".join(map(q, names))
    select = "SELECT " + colsql + " FROM " + q(t)
    rows = src.execute(select).fetchall()
    expected = []
    for row in rows:
        values: list[object] = []
        digest: list[object] = []
        for (n, k), v in zip(cols, row, strict=False):
            try:
                if k in ("json", "jsonb") and v is not None:
                    obj = json.loads(v)
                    values.append((Json if k == "json" else Jsonb)(obj))
                    digest.append(json.dumps(obj, sort_keys=True))
                else:
                    norm = convert(v, k)
                    values.append(norm)
                    digest.append(norm)
            except Exception:
                raise ValueError((name, t, n, k, "conversion")) from None
        try:
            db.execute(
                "INSERT INTO "
                + q(t)
                + " ("
                + colsql
                + ") VALUES ("
                + ",".join(["%s"] * len(cols))
                + ")",
                values,
            )
        except psycopg.Error as ex:
            raise ValueError((name, t, ex.sqlstate, ex.diag.column_name)) from None
        expected.append(tuple(digest))
    # Cast JSON to text to distinguish SQL NULL and JSON null.
    sel = ",".join(q(n) + ("::text" if k in ("json", "jsonb") else "") for n, k in cols)
    actual = [
        tuple(
            json.dumps(json.loads(v), sort_keys=True)
            if k in ("json", "jsonb") and v is not None
            else convert(v, k)
            for (_, k), v in zip(cols, r, strict=False)
        )
        for r in db.execute("SELECT " + sel + " FROM " + q(t))
    ]
    if collections.Counter(actual) != collections.Counter(expected):
        msg = "Values differ after transfer: " + name + "/" + t
        raise RuntimeError(msg)
    for n, seq in db.execute(
        "select column_name,pg_get_serial_sequence(%s,column_name) "
        "from information_schema.columns where table_schema='public' and table_name=%s "
        "and (is_identity='YES' or column_default like 'nextval%%')",
        (q(t), t),
    ).fetchall():
        if seq and rows:
            db.execute(
                "select setval(%s,(select max(" + q(n) + ") from " + q(t) + "),true)",
                (seq,),
            )
    return len(rows)


def move(name: str, src: sqlite3.Connection, db: psycopg.Connection) -> None:
    """Move one reviewed NetBird source database into its isolated target."""
    _verify_sqlite(src)
    tables = _verify_pg_ready(name, src, db)
    deps = list(
        db.execute(
            "select t.relname,p.relname from pg_constraint c "
            "join pg_class t on t.oid=c.conrelid join pg_class p on p.oid=c.confrelid "
            "where c.contype='f' and t.relnamespace='public'::regnamespace"
        )
    )
    done: set[str] = set()
    db.execute("TRUNCATE " + ",".join(map(q, sorted(tables))) + " RESTART IDENTITY")
    total = 0
    while tables - done:
        batch = [
            t
            for t in sorted(tables - done)
            if all(p == t or p in done for child, p in deps if child == t)
        ]
        if not batch:
            msg = "Foreign-key cycle among remaining tables: " + name
            raise RuntimeError(msg)
        for t in batch:
            total += _copy_table(name, t, src, db)
            done.add(t)
    print(name, len(tables), "tables", total, "rows verified", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode not in ("cold", "trial"):
        msg = "Mode must be cold or trial"
        raise RuntimeError(msg)
    names = sys.argv[2:]
    if not names:
        msg = "At least one source short name is required"
        raise RuntimeError(msg)
    if not set(names) <= NAMES.keys():
        msg = "Unknown source short name requested"
        raise RuntimeError(msg)
    for name in names:
        f = name + ".db"
        url = (pathlib.Path("/dsn") / f).read_text()
        p = urlparse(url)
        if p.hostname != "pg-critical-rw.postgres.svc.cluster.local":
            msg = "Transfer target must be the in-cluster pg-critical writer service"
            raise RuntimeError(msg)
        if p.path != "/" + NAMES[name]:
            msg = "Target path must map the source to its reviewed database"
            raise RuntimeError(msg)
        if "sslmode=verify-full" not in p.query:
            msg = "Target connection must require sslmode=verify-full"
            raise RuntimeError(msg)
        with tempfile.TemporaryDirectory() as directory:
            srcpath = pathlib.Path("/src") / f
            dest = pathlib.Path(directory) / f
            if mode == "cold":
                for suffix in ("", "-wal", "-journal"):
                    orig = pathlib.Path(str(srcpath) + suffix)
                    if orig.exists():
                        shutil.copyfile(orig, str(dest) + suffix)
            else:
                with (
                    sqlite3.connect(srcpath.as_uri() + "?mode=ro", uri=True) as live,
                    sqlite3.connect(dest) as out,
                ):
                    live.backup(out)
            with sqlite3.connect(dest) as src, psycopg.connect(url) as db:
                db.execute("SET LOCAL TIME ZONE 'UTC'")
                move(name, src, db)
