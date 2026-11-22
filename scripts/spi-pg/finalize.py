"""Reconcile final cold SPI source to the verified preseed. Compare every field, including large text as SHA-256."""

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


def reconcile(src, db, apply):
    src.execute("BEGIN")
    assert (
        src.execute("pragma integrity_check").fetchall() == [("ok",)]
        and not src.execute("pragma foreign_key_check").fetchone()
    )
    tabs = [
        r[0]
        for r in src.execute(
            "select name from sqlite_master where type='table' order by rowid"
        )
    ]
    assert len(tabs) == 19 and set(tabs) == {
        r[0]
        for r in db.execute("select tablename from pg_tables where schemaname='public'")
    }
    db.execute("select pg_advisory_xact_lock(1397770578)")
    # Handoff has a different lock during the bulk import; the final activation is a separate short transaction.
    changes = deletes = total = 0
    todo = []
    for t in tabs:
        cols = src.execute("pragma table_info(" + t + ")").fetchall()
        names = [r[1] for r in cols]
        types = [r[2].upper() for r in cols]
        keys = [r[1] for r in sorted(cols, key=lambda r: r[5]) if r[5]]
        assert keys and names == [
            r[0]
            for r in db.execute(
                "select column_name from information_schema.columns where table_schema='public' and table_name=%s order by ordinal_position",
                (t,),
            )
        ]
        join = lambda a: sql.SQL(",").join(map(sql.Identifier, a))
        pgsig = sql.SQL(",").join(
            sql.SQL("sha256(convert_to({},'UTF8'))").format(sql.Identifier(n))
            if typ == "TEXT"
            else sql.Identifier(n)
            for n, typ in zip(names, types)
        )
        query = sql.SQL("select {},{} from {}").format(
            join(keys), pgsig, sql.Identifier(t)
        )

        def pgmap():
            with db.cursor(name="checked_rows") as c:
                c.itersize = 500
                c.execute(query)
                return {tuple(r[: len(keys)]): tuple(r[len(keys) :]) for r in c}

        old = pgmap()
        expected = {}
        nonkeys = [n for n in names if n not in keys]
        action = (
            sql.SQL("DO UPDATE SET ")
            + sql.SQL(",").join(
                sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(n), sql.Identifier(n))
                for n in nonkeys
            )
            if nonkeys
            else sql.SQL("DO NOTHING")
        )
        up = (
            sql.SQL("insert into {} ({}) values ({}) on conflict ({}) ").format(
                sql.Identifier(t),
                join(names),
                sql.SQL(",").join(sql.Placeholder() for _ in names),
                join(keys),
            )
            + action
        )
        pending = []
        for row in src.execute("select * from " + t):
            key = tuple(row[names.index(n)] for n in keys)
            sig = tuple(
                hashlib.sha256(v.encode()).digest()
                if typ == "TEXT" and v is not None
                else v
                for typ, v in zip(types, row)
            )
            expected[key] = sig
            if old.get(key) != sig:
                pending.append(row)
                changes += 1
                if len(pending) >= 16:
                    with db.cursor() as writer:
                        writer.executemany(up, pending)
                    pending = []
        if pending:
            with db.cursor() as writer:
                writer.executemany(up, pending)
        extras = old.keys() - expected.keys()
        delete = sql.SQL("delete from {} where ").format(sql.Identifier(t)) + sql.SQL(
            " AND "
        ).join(sql.SQL("{}=%s").format(sql.Identifier(n)) for n in keys)
        todo.append((query, len(keys), expected, delete, extras))
        total += len(expected)
    for _, _, _, q, extra in reversed(todo):
        for k in extra:
            db.execute(q, k)
            deletes += 1
    for q, n, expected, _, _ in todo:
        with db.cursor(name="final_verify") as c:
            c.itersize = 500
            c.execute(q)
            actual = {tuple(r[:n]): tuple(r[n:]) for r in c}
            assert actual == expected, "Final typed receipt differs"
    for t in ("llm_admission", "queue_operator_actions"):
        db.execute(
            sql.SQL(
                "SELECT setval(pg_get_serial_sequence(%s,'id'),coalesce(max(id),1),count(*)>0) FROM {}"
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
    mode = sys.argv[1]
    assert mode in ("seed", "cold")
    u = os.environ["SPI_POSTGRES_URL"]
    info = conninfo_to_dict(u)
    assert (
        info["dbname"] == "spi_triage"
        and info["host"] == "pg-common-rw.postgres.svc.cluster.local"
        and info["sslmode"] == "verify-full"
    )
    with tempfile.TemporaryDirectory() as tmp, psycopg.connect(u) as db:
        assert db.execute("select live from handoff.mode").fetchone() == (False,)
        if mode == "seed":
            assert not db.execute(
                "select from pg_tables where schemaname='public'"
            ).fetchone()
            db.execute(Path(__file__).with_name("schema.sql").read_text())
            p = Path("/src/.spi-pg-rehearsal.sqlite")
        else:
            p = Path(tmp) / "spi.sqlite"
            for suff in ("", "-wal", "-journal"):
                f = Path("/src") / (p.name + suff)
                if f.exists():
                    shutil.copyfile(f, str(p) + suff)
        with sqlite3.connect(p.as_uri() + "?mode=ro", uri=True) as src:
            reconcile(src, db, mode == "cold")
