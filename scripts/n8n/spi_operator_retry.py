#!/usr/bin/env python3
"""Offline-reviewed, private operator CLI. Default dry-run; never a public API.

No allowance reset: one subsequent unsafe failure can kill a selected job again.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import TypedDict, cast

TARGETS = {
    "08ba1f0938dd3bf6d8a03b9383b5d852255bbd16fa6c24ba6ece198c0a503af9": "LLM_CONTEXT_METADATA_TOO_LARGE",
    "998bcead172052e72c281f3cd1d312c4f82412002ecf40232da6c6631b45e362": "UPSTREAM_TIMEOUT",
}
NONCE = "spi-two-target-retry-08ba-998b-20261107-v1"
AUDIT = "operator_retry_audit"


_Job = dict[str, object]
_AuditEntry = tuple[str, str, str, str, float, str, str, str, str]


class _Authorization(TypedDict, total=False):
    """Fields consulted when checking a recorded authorization."""

    authorization_text: str
    nonce: str
    job_ids: list[str]
    reason: str
    recorded_at: str
    supervisor_run_id: str
    target_manifest_digest: str


def packed(x: object) -> str:
    """Serialize a value to a canonical, stable JSON encoding."""
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(x: object) -> str:
    """Return the SHA-256 hex digest of the canonical JSON encoding of x."""
    return hashlib.sha256(packed(x).encode()).hexdigest()


def quoted(name: str) -> str:
    """Quote an identifier for embedding into SQLite SQL."""
    return '"' + name.replace('"', '""') + '"'


def ordered_table_scan(c: sqlite3.Connection, name: str) -> sqlite3.Cursor:
    """Transaction-local physical order, not a VACUUM-independent logical hash.

    Never sort complete rows: require the native rowid/primary btree order and
    check the actual planner before streaming. Unsupported schemas fail closed.
    """
    tables = list(c.execute("PRAGMA main.table_list"))
    matches = [r for r in tables if r[1] == name]
    if len(matches) != 1 or matches[0][2] != "table":
        msg = "unsupported table kind"
        raise ValueError(msg)
    q = quoted(name)
    info = list(c.execute("PRAGMA main.table_xinfo(" + q + ")"))
    if not info:
        msg = "unsupported table columns"
        raise ValueError(msg)
    if matches[0][4]:  # WITHOUT ROWID: declared primary key is the table btree.
        keys = sorted((r for r in info if r[5]), key=lambda r: r[5])
        if not keys:
            msg = "missing WITHOUT ROWID primary key"
            raise ValueError(msg)
        order = ",".join(quoted(r[1]) for r in keys)
    else:
        names = {r[1].lower() for r in info}
        alias = next((a for a in ("rowid", "_rowid_", "oid") if a not in names), None)
        if alias is None:
            # Refuse rather than risk an index sort or a nullable/nonunique key.
            msg = "all rowid aliases shadowed: unsupported schema"
            raise ValueError(msg)
        order = quoted(alias)
    sql = "SELECT * FROM main." + q + " ORDER BY " + order
    plan = list(c.execute("EXPLAIN QUERY PLAN " + sql))
    if not plan or any("TEMP B-TREE" in r[3].upper() for r in plan):
        msg = "table scan requires temporary sort"
        raise ValueError(msg)
    return c.execute(sql)


def table_hashes(
    c: sqlite3.Connection, original_jobs: dict[str, _Job] | None = None
) -> dict[str, str]:
    """Hash every non-audit table row-by-row in stable btree order."""
    result = {}
    for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if name == AUDIT:
            continue
        # Whole rows, streamed in stable btree order within BEGIN IMMEDIATE.
        # Memory is bounded by a row and its serialized representation.
        h = hashlib.sha256()
        for row in ordered_table_scan(c, name):
            if name == "jobs" and original_jobs and row["id"] in original_jobs:
                row = [original_jobs[row["id"]][k] for k in row.keys()]
            h.update(
                packed([{"blob": v.hex()} if isinstance(v, bytes) else v for v in row]).encode()
                + b"\n"
            )
        result[name] = h.hexdigest()
    return result


def _checked_manifest(manifest: object) -> tuple[str, list[dict[object, object]]]:
    """Return the digest and the very rows checked against the reviewed target IDs."""
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != 1
        or manifest.get("nonce") != NONCE
        or not re.fullmatch(r"[0-9a-f]{64}", manifest.get("original_target_file_sha256", ""))
    ):
        msg = "invalid target manifest"
        raise ValueError(msg)
    rows = manifest.get("rows")
    if (
        not isinstance(rows, list)
        or len(rows) != 2
        or any(not isinstance(r, dict) for r in rows)
        or {r.get("id") for r in rows} != set(TARGETS)
    ):
        msg = "invalid manifest IDs"
        raise ValueError(msg)
    return digest(manifest), rows


def manifest_digest(manifest: object) -> str:
    """Validate the reviewed target manifest and return its canonical digest."""
    checksum, _ = _checked_manifest(manifest)
    return checksum


def authorize(a: _Authorization) -> None:
    """Validate the recorded operator authorization against the expected nonce and reasons."""
    if (
        a.get("authorization_text") != "Да, все рзрешаю"
        or a.get("nonce") != NONCE
        or set(a.get("job_ids", [])) != set(TARGETS)
        or len(a["job_ids"]) != 2
        or not a.get("reason")
        or not a.get("recorded_at")
        or a.get("supervisor_run_id") != "497906c9-c254-4586-9762-e1aa195b8f24"
    ):
        msg = "authorization mismatch"
        raise ValueError(msg)
    datetime.datetime.fromisoformat(a["recorded_at"])


def _require_retryable(row: dict[str, object], error: str) -> None:
    """Refuse unless the row is dead, unleased, and matches the reviewed failure."""
    if row["state"] == "complete" and row["stage"] == 2:
        msg = "already complete: skip, never rerun"
        raise ValueError(msg)
    if (
        row["state"] != "dead"
        or row["stage"] != 2
        or row["lease"] != 0
        or row["error"] != error
        or row["intent"] is not None
    ):
        msg = "unexpected state/stage/lease/error/intent"
        raise ValueError(msg)


def _reviewed_selected_rows(c: sqlite3.Connection, rows: list[dict[object, object]]) -> list[_Job]:
    """Validate the exact selected rows and their episode isolation."""
    selected = []
    for key, error in TARGETS.items():
        matches = list(c.execute("SELECT * FROM jobs WHERE id=?", (key,)))
        if len(matches) != 1:
            msg = "missing exact full ID"
            raise ValueError(msg)
        row = dict(matches[0])
        if row != next(r for r in rows if r["id"] == key):
            msg = "reviewed full row drift"
            raise ValueError(msg)
        _require_retryable(row, error)
        if c.execute(
            "SELECT 1 FROM jobs WHERE episode=? AND (intent IS NOT NULL OR state='complete') "
            "LIMIT 1",
            (row["episode"],),
        ).fetchone():
            msg = "episode publication or active intent"
            raise ValueError(msg)
        selected.append(row)
    return selected


def _require_fresh_audit(c: sqlite3.Connection) -> None:
    """Refuse execution if the once-only authorization nonce is already recorded."""
    if AUDIT in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        if c.execute(
            "SELECT 1 FROM operator_retry_audit WHERE nonce=? LIMIT 1", (NONCE,)
        ).fetchone():
            msg = "authorization nonce already consumed"
            raise ValueError(msg)


def _prepare_audit(c: sqlite3.Connection) -> tuple[list[object], list[_AuditEntry]]:
    """Create the immutable audit table/triggers and snapshot the prior state."""
    c.execute(
        "CREATE TABLE IF NOT EXISTS operator_retry_audit (nonce TEXT NOT NULL, job_id TEXT NOT NULL, authorization_hash TEXT NOT NULL, pre_row_hash TEXT NOT NULL, executed_at REAL NOT NULL, reason TEXT NOT NULL, explicit_change TEXT NOT NULL, manifest_digest TEXT NOT NULL, post_row_hash TEXT NOT NULL, PRIMARY KEY(nonce,job_id))"
    )
    for action in ("UPDATE", "DELETE"):
        name = "operator_retry_audit_no_" + action.lower()
        sql = (
            "CREATE TRIGGER "
            + name
            + " BEFORE "
            + action
            + " ON operator_retry_audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END"
        )
        existing = c.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if existing is None:
            c.execute(sql)
        elif existing[0] != sql:
            msg = "audit immutability schema mismatch"
            raise ValueError(msg)
    if c.execute("SELECT count(*) FROM operator_retry_audit").fetchone()[0] + 2 > 2:
        msg = "bounded audit full"
        raise ValueError(msg)
    audit_schema = list(
        c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
    )
    audit_before = [
        tuple(r) for r in c.execute("SELECT * FROM operator_retry_audit ORDER BY nonce,job_id")
    ]
    return audit_schema, audit_before


def _mutate_reviewed_rows(
    c: sqlite3.Connection,
    rows: list[_Job],
    authorization: _Authorization,
    bound: str,
    expected_audit: list[_AuditEntry],
) -> float:
    """Apply the retry UPDATE and audit INSERT for each reviewed row."""
    now = time.time()
    for row in rows:
        change = {"state": "retry", "available": now, "updated": now}
        c.execute(
            "UPDATE jobs SET state=?,available=?,updated=? WHERE id=?",
            ("retry", now, now, row["id"]),
        )
        entry: _AuditEntry = (
            NONCE,
            cast("str", row["id"]),
            digest(authorization),
            digest(row),
            now,
            authorization["reason"],
            packed(change),
            bound,
            digest(dict(row, **change)),
        )
        c.execute("INSERT INTO operator_retry_audit VALUES(?,?,?,?,?,?,?,?,?)", entry)
        expected_audit.append(entry)
        actual = dict(c.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())
        if actual != dict(row, **change):
            msg = "unexpected selected row mutation"
            raise ValueError(msg)
    return now


def _verify_targets(c: sqlite3.Connection, rows: list[_Job], now: float) -> None:
    """Confirm only the two reviewed rows now hold the retry state."""
    expected = {r["id"]: dict(r, state="retry", available=now, updated=now) for r in rows}
    for key, row in expected.items():
        if dict(c.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()) != row:
            msg = "final target mismatch"
            raise ValueError(msg)


def _verify_audit_state(
    c: sqlite3.Connection, expected_audit: list[_AuditEntry], audit_schema: list[object]
) -> None:
    """Confirm the audit content and schema changed exactly as authorized."""
    actual_audit = [
        tuple(r) for r in c.execute("SELECT * FROM operator_retry_audit ORDER BY nonce,job_id")
    ]
    actual_schema = list(
        c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
    )
    if actual_audit != sorted(expected_audit, key=lambda r: (r[0], r[1])) or (
        actual_schema != audit_schema
    ):
        msg = "audit content/schema mismatch"
        raise ValueError(msg)


def retry(
    path: str | Path,
    authorization: _Authorization,
    execute: bool = False,
    manifest: object = None,
) -> dict[str, object]:
    """Verify state and re-queue the two reviewed dead jobs under immutable audit."""
    if os.environ.get("SPI_POSTGRES_URL"):
        msg = "Historical SQLite-only tool; refusing a PostgreSQL deployment"
        raise ValueError(msg)
    authorize(authorization)
    bound, manifest_rows = _checked_manifest(manifest)
    if authorization.get("target_manifest_digest") != bound:
        msg = "authorization manifest mismatch"
        raise ValueError(msg)
    c = sqlite3.connect("file:" + str(path) + "?mode=rw", uri=True, isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("BEGIN IMMEDIATE")
        before = table_hashes(c)
        rows = _reviewed_selected_rows(c, manifest_rows)
        _require_fresh_audit(c)
        if not execute:
            c.rollback()
            return {
                "mode": "DRY_RUN",
                "eligible": 2,
                "row_hashes": {r["id"]: digest(r) for r in rows},
            }
        audit_schema, audit_before = _prepare_audit(c)
        expected_audit = list(audit_before)
        # Normalize only the two already-verified selected rows while hashing;
        # no compensating UPDATEs or history rewrites are performed.
        now = _mutate_reviewed_rows(c, rows, authorization, bound, expected_audit)
        if table_hashes(c, {cast("str", r["id"]): r for r in rows}) != before:
            msg = "non-authorized row/table mutation"
            raise ValueError(msg)
        _verify_targets(c, rows, now)
        _verify_audit_state(c, expected_audit, audit_schema)
        c.commit()
        return {
            "mode": "EXECUTED",
            "changed": 2,
            "authorization_hash": digest(authorization),
        }
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def main() -> None:
    """Parse CLI arguments and run the dry-run or executed retry."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", required=True)
    p.add_argument("--authorization", required=True)
    p.add_argument("--target-manifest", required=True)
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    with open(a.authorization) as f:
        auth = json.load(f)
    with open(a.target_manifest) as f:
        manifest = json.load(f)
    print(packed(retry(a.database, auth, a.execute, manifest)))


if __name__ == "__main__":
    main()
