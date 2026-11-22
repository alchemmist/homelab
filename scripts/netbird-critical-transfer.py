"""NetBird v0.83.2 offline transfer into isolated, freshly provisioned pg-critical databases.
Never reuse against a live database. Caller must stop all target writers. Dex keeps its native migration ledger.
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
from urllib.parse import urlparse

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


def q(n):
    assert re.fullmatch("[a-zA-Z_][a-zA-Z_0-9]*", n)
    return '"' + n + '"'


def convert(v, k):
    if v is None:
        return None
    if k == "bool":
        if v not in (True, False, 0, 1):
            raise ValueError("unexpected boolean")
        return bool(v)
    if k == "timestamptz":
        if isinstance(v, str):
            v = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return (v if v.tzinfo else v.replace(tzinfo=dt.UTC)).astimezone(dt.UTC)
    if k == "bytea":
        return v.encode() if isinstance(v, str) else bytes(v)
    if k in ("int4", "int8"):
        return int(v)
    if k == "numeric":
        return decimal.Decimal(str(v))
    return v


def move(name, src, db):
    assert (
        src.execute("pragma integrity_check").fetchall() == [("ok",)]
        and not src.execute("pragma foreign_key_check").fetchone()
    )
    st = {
        r[0]
        for r in src.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
        )
    }
    pt = {r[0] for r in db.execute("select tablename from pg_tables where schemaname='public'")}
    assert st == pt, (name, st ^ pt)
    tables = set(st)
    if name == "idp":
        tables.remove("migrations")
        assert (
            db.execute("select count(*) from migrations").fetchone()[0] == 22
            and src.execute("select count(*) from migrations").fetchone()[0] == 23
        )
    if name == "store":
        for n, typ in LEGACY.items():
            db.execute("ALTER TABLE peers ADD COLUMN IF NOT EXISTS " + q(n) + " " + typ)
    deps = list(
        db.execute(
            "select t.relname,p.relname from pg_constraint c "
            "join pg_class t on t.oid=c.conrelid join pg_class p on p.oid=c.confrelid "
            "where c.contype='f' and t.relnamespace='public'::regnamespace"
        )
    )
    done = set()
    db.execute("TRUNCATE " + ",".join(map(q, sorted(tables))) + " RESTART IDENTITY")
    total = 0
    while tables - done:
        batch = [
            t
            for t in sorted(tables - done)
            if all(p == t or p in done for child, p in deps if child == t)
        ]
        assert batch, "fk cycle"
        for t in batch:
            cols = list(
                db.execute(
                    "select column_name,udt_name from information_schema.columns "
                    "where table_schema='public' and table_name=%s order by ordinal_position",
                    (t,),
                )
            )
            names = [n for n, _ in cols]
            assert set(names) == {r[1] for r in src.execute("pragma table_info(" + q(t) + ")")}, (
                name,
                t,
                "column mismatch",
            )
            colsql = ",".join(map(q, names))
            select = "SELECT " + colsql + " FROM " + q(t)
            rows = src.execute(select).fetchall()
            expected = []
            for row in rows:
                values = []
                digest = []
                for (n, k), v in zip(cols, row):
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
                    for (_, k), v in zip(cols, r)
                )
                for r in db.execute("SELECT " + sel + " FROM " + q(t))
            ]
            assert collections.Counter(actual) == collections.Counter(expected), (
                name,
                t,
                "values differ",
            )
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
            total += len(rows)
            done.add(t)
    print(name, len(tables), "tables", total, "rows verified", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1]
    assert mode in ("cold", "trial")
    names = sys.argv[2:]
    assert names and set(names) <= NAMES.keys()
    for name in names:
        f = name + ".db"
        url = (pathlib.Path("/dsn") / f).read_text()
        p = urlparse(url)
        assert (
            p.hostname == "pg-critical-rw.postgres.svc.cluster.local"
            and p.path == "/" + NAMES[name]
            and "sslmode=verify-full" in p.query
        )
        with tempfile.TemporaryDirectory() as d:
            srcpath = pathlib.Path("/src") / f
            dest = pathlib.Path(d) / f
            if mode == "cold":
                for suff in ("", "-wal", "-journal"):
                    orig = pathlib.Path(str(srcpath) + suff)
                    if orig.exists():
                        shutil.copyfile(orig, str(dest) + suff)
            else:
                with (
                    sqlite3.connect(srcpath.as_uri() + "?mode=ro", uri=True) as live,
                    sqlite3.connect(dest) as out,
                ):
                    live.backup(out)
            with sqlite3.connect(dest) as src, psycopg.connect(url) as db:
                db.execute("SET LOCAL TIME ZONE 'UTC'")
                move(name, src, db)
