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

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


def receipt(rows):
    return collections.Counter(
        hashlib.sha256(
            json.dumps(
                tuple(row), ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode()
        ).digest()
        for row in rows
    )


def transfer(src, db):
    src.execute("BEGIN")
    assert (
        src.execute("pragma integrity_check").fetchall() == [("ok",)]
        and not src.execute("pragma foreign_key_check").fetchone()
    )
    assert not db.execute("select from pg_tables where schemaname='public'").fetchone()
    db.execute(Path(__file__).with_name("schema.sql").read_text())
    tabs = [
        r[0]
        for r in src.execute("select name from sqlite_master where type='table' order by rowid")
    ]
    assert len(tabs) == 19 and set(tabs) == {
        r[0] for r in db.execute("select tablename from pg_tables where schemaname='public'")
    }
    total = 0
    for t in tabs:
        table = sql.Identifier(t)
        cols = [r[1] for r in src.execute("pragma table_info(" + t + ")")]
        assert cols == [
            r[0]
            for r in db.execute(
                "select column_name from information_schema.columns where table_schema='public' and table_name=%s order by ordinal_position",
                (t,),
            )
        ]
        columns = sql.SQL(",").join(map(sql.Identifier, cols))
        expected = collections.Counter()
        source_rows = src.execute("select * from " + t)
        while batch := source_rows.fetchmany(8):
            with db.cursor().copy(sql.SQL("COPY {} ({}) FROM STDIN").format(table, columns)) as cp:
                for row in batch:
                    cp.write_row(row)
            expected.update(receipt(batch))
        with db.cursor(name="verify_rows") as c:
            c.itersize = 16
            c.execute(sql.SQL("SELECT {} FROM {}").format(columns, table))
            assert receipt(c) == expected, (t, "receipt mismatch")
        total += sum(expected.values())
        print(t, sum(expected.values()), flush=True)
    for t in ("llm_admission", "queue_operator_actions"):
        db.execute(
            sql.SQL(
                "SELECT setval(pg_get_serial_sequence(%s,'id'),coalesce(max(id),1),count(*)>0) FROM {}"
            ).format(sql.Identifier(t)),
            (t,),
        )
    return total


if __name__ == "__main__":
    mode = sys.argv[1]
    assert mode in ("trial", "cold")
    url = os.environ["SPI_POSTGRES_URL"]
    params = conninfo_to_dict(url)
    assert (
        params["host"] == "pg-common-rw.postgres.svc.cluster.local"
        and params["dbname"] == "spi_triage"
        and params["sslmode"] == "verify-full"
    )
    p = Path("/src/.spi-pg-rehearsal.sqlite" if mode == "trial" else "/src/spi.sqlite")
    with tempfile.TemporaryDirectory() as tmp:
        if mode == "cold":
            for suffix in ("", "-wal", "-journal"):
                f = Path(str(p) + suffix)
                if f.exists():
                    shutil.copyfile(f, Path(tmp) / f.name)
            p = Path(tmp) / p.name
        with (
            sqlite3.connect(p.as_uri() + "?mode=ro", uri=True) as src,
            psycopg.connect(url) as dst,
        ):
            total = transfer(src, dst)
            if mode == "trial":
                dst.rollback()
            print("verified total", total, mode, flush=True)
