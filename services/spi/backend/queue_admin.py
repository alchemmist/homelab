"""Small operator DTO and atomic cancellation. No execution or retry controls."""

import hmac
import math
import re
import time
from collections.abc import Mapping
from email.message import Message
from typing import cast

from core import Failure, Store

STATES = (
    "queued",
    "retry",
    "processing",
    "dead",
    "complete",
    "cancelled",
    "dry_run",
)
PENDING_VIEW = ("processing", "queued", "retry")
OWNED_PHASES = ("ready", "waiting", "running", "complete")
QUEUE_HEADER = "X-Queue-Token"
MIN_QUEUE_TOKEN_CHARS = 32
MAX_QUEUE_HEADER_CHARS = 128
DEFAULT_LIST_LIMIT = 25
MAX_LIST_LIMIT = 100
MAX_LIST_OFFSET = 100000
PIPELINE_JOBS = 1
REQUESTS_PER_MINUTE = 3
REQUEST_TOKENS = 30000
MAX_CANCEL_BATCH = 4000
MAX_SORT_VALUE_CHARS = 200
JOB_ID_PATTERN = "[0-9a-f]{64}"
# Fixed SQL identifiers only; no client text is interpolated into SQL.
SORTS = {
    "created": ("created", "id"),
    "alert": ("sort_alert", "created", "id"),
    "state": ("sort_state", "stage", "created", "id"),
    "progress": ("sort_progress", "attempts", "failures", "created", "id"),
}
SORT_DIRECTIONS = ("asc", "desc")
CODE_INVALID_QUERY = "INVALID_QUEUE_QUERY"
CODE_INVALID_CANCEL = "INVALID_QUEUE_CANCEL"
CODE_JOB_NOT_FOUND = "JOB_NOT_FOUND"
CODE_ITEM_CHANGED = "QUEUE_ITEM_CHANGED"
CODE_NOT_CANCELLABLE = "QUEUE_ITEM_NOT_CANCELLABLE"
CODE_INVALID_CANCEL_BATCH = "INVALID_QUEUE_CANCEL_BATCH"
AUDIT_SOURCE = "private-sso-queue-ui"


def authorized(headers: Message, token: str) -> bool:
    """Accept one exact dedicated queue token from a single header instance."""
    values = headers.get_all(QUEUE_HEADER, [])
    return (
        len(token) >= MIN_QUEUE_TOKEN_CHARS
        and len(values) == 1
        and len(values[0]) <= MAX_QUEUE_HEADER_CHARS
        and hmac.compare_digest(values[0].encode("utf-8"), token.encode("utf-8"))
    )


class QueueAdmin:
    """Read-only operator listing plus one atomic, audited state transition."""

    def __init__(self, store: Store) -> None:
        """Mount the audit table on one reviewed store."""
        self.store = store
        with store.db() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS queue_operator_actions (
                id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                action TEXT NOT NULL, at REAL NOT NULL,
                previous_state TEXT NOT NULL, previous_error TEXT, previous_updated REAL NOT NULL,
                source TEXT NOT NULL CHECK(source='private-sso-queue-ui'))"""
            )

    def list(self, data: Mapping[str, object]) -> dict[str, object]:
        """Return the minimal operator DTO page: counts, bounded rows and limits."""
        state = data.get("state", "pending")
        offset = data.get("offset", 0)
        limit = data.get("limit", DEFAULT_LIST_LIMIT)
        sort = data.get("sort", "created")
        direction = data.get("direction", "asc")
        after = data.get("after")
        if (
            state not in ("pending", *STATES)
            or type(offset) is not int
            or not 0 <= offset <= MAX_LIST_OFFSET
            or type(limit) is not int
            or not 1 <= limit <= MAX_LIST_LIMIT
            or not isinstance(sort, str)
            or sort not in SORTS
            or direction not in SORT_DIRECTIONS
        ):
            raise Failure(CODE_INVALID_QUERY)
        columns = cast("tuple[str, ...]", SORTS[sort])
        values: list[object] = []
        if after is not None:
            if (
                not isinstance(after, Mapping)
                or set(after) != {"sort", "direction", "values"}
                or after["sort"] != sort
                or after["direction"] != direction
                or offset
                or not isinstance(after["values"], list)
                or len(after["values"]) != len(columns)
            ):
                raise Failure(CODE_INVALID_QUERY)
            values = list(after["values"])
            for column, value in zip(columns, values, strict=True):
                if column in ("id", "sort_alert"):
                    if (
                        not isinstance(value, str)
                        or len(value) > MAX_SORT_VALUE_CHARS
                        or (column == "id" and not re.fullmatch(JOB_ID_PATTERN, value))
                    ):
                        raise Failure(CODE_INVALID_QUERY)
                elif type(value) not in (int, float) or not math.isfinite(value):
                    raise Failure(CODE_INVALID_QUERY)
        selected = PENDING_VIEW if state == "pending" else (cast("str", state),)
        now = time.time()
        with self.store.db() as c:
            counts = {
                r["state"]: r["n"]
                for r in c.execute("SELECT state,count(*) n FROM jobs GROUP BY state")
            }
            where = "j.state IN (" + ",".join("?" for _ in selected) + ")"
            fetched = c.execute("SELECT count(*) FROM jobs j WHERE " + where, selected).fetchone()
            total = fetched[0]
            query = (
                """SELECT * FROM (SELECT j.id,j.state,j.stage,j.created,j.updated,j.available,
                j.attempts,j.error,j.issue,
                j.intent IS NOT NULL AS has_intent,
                json_extract(j.result,'$.primary_publication') IS NOT NULL AS has_primary,
                substr(json_extract(j.event,'$.labels.alertname'),1,200) AS alertname,
                substr(json_extract(j.event,'$.labels.instance'),1,200) AS instance,
                substr(json_extract(j.event,'$.labels.namespace'),1,120) AS namespace,
                substr(json_extract(j.event,'$.labels.severity'),1,80) AS severity,
                json_extract(j.event,'$.status') AS alert_status,
                substr(json_extract(j.event,'$.annotations.summary'),1,400) AS summary,
                coalesce(b.failures,0) AS failures,
                o.execution_id,o.phase AS owner_phase,o.stage AS owner_stage,o.due,o.deadline,
                json_array_length(json_extract(j.result,'$.match_progress_v3.reviews'))
                    AS review_batches,
                json_array_length(json_extract(j.result,'$.match_progress_v3.snapshot'))
                    AS review_catalog,
                o.phase IN ('ready','waiting','running','complete') AS owned,
                coalesce(substr(json_extract(j.event,'$.labels.alertname'),1,200),'')
                    COLLATE NOCASE AS sort_alert,
                CASE j.state WHEN 'queued' THEN 0 WHEN 'retry' THEN 1
                  WHEN 'processing' THEN 2 WHEN 'dead' THEN 3 WHEN 'complete' THEN 4
                  WHEN 'cancelled' THEN 5 ELSE 6 END AS sort_state,
                coalesce(json_array_length(json_extract(j.result,'$.match_progress_v3.reviews')),0)
                    AS sort_progress
                FROM jobs j LEFT JOIN job_failure_budget b ON b.job_id=j.id
                LEFT JOIN workflow_wait_owner o ON o.job_id=j.id WHERE """
                + where
                + ") AS q"
            )
            if after is not None:
                query += (
                    " WHERE ("
                    + ",".join(columns)
                    + ") "
                    + (">" if direction == "asc" else "<")
                    + " ("
                    + ",".join("?" for _ in columns)
                    + ")"
                )
            query += (
                " ORDER BY "
                + ",".join(column + " " + direction for column in columns)
                + " LIMIT ? OFFSET ?"
            )
            rows = c.execute(query, (*selected, *values, limit + 1, offset)).fetchall()
            page = rows[:limit]
            cursor = (
                {
                    "sort": sort,
                    "direction": direction,
                    "values": [page[-1][column] for column in columns],
                }
                if len(rows) > limit
                else None
            )
            items: list[dict[str, object]] = []
            for r in page:
                item = dict(r)
                item["can_cancel"] = (
                    r["state"] in ("queued", "retry")
                    and not r["owned"]
                    and not r["has_intent"]
                    and not r["has_primary"]
                    and not r["issue"]
                )
                for key in (
                    "owned",
                    "has_intent",
                    "has_primary",
                    "sort_alert",
                    "sort_state",
                    "sort_progress",
                ):
                    del item[key]
                items.append(item)
        return {
            "now": now,
            "counts": counts,
            "total": total,
            "offset": offset,
            "limit": limit,
            "sort": sort,
            "direction": direction,
            "next_cursor": cursor,
            "items": items,
            "limits": {
                "parallel_jobs": PIPELINE_JOBS,
                "requests_per_minute": REQUESTS_PER_MINUTE,
                "tokens_per_minute": self.store.minute_token_limit,
                "request_tokens": REQUEST_TOKENS,
            },
        }

    def cancel_batch(self, data: Mapping[str, object]) -> dict[str, object]:
        """One fenced transaction, one wake. Never cancel a live owner/publication.

        The temporary tables are connection-local, memory-backed and bounded.
        Audits and job updates commit together or all roll back on any failure.
        """
        requests = data.get("items")
        if (
            not isinstance(requests, list)
            or not 1 <= len(requests) <= MAX_CANCEL_BATCH
            or set(data) != {"items"}
        ):
            raise Failure(CODE_INVALID_CANCEL_BATCH)
        values: list[tuple[str, object]] = []
        seen: set[str] = set()
        for item in requests:
            if not isinstance(item, Mapping) or set(item) != {"job_id", "expected_updated"}:
                raise Failure(CODE_INVALID_CANCEL_BATCH)
            key = item["job_id"]
            expected = item["expected_updated"]
            try:
                valid_version = type(expected) in (int, float) and math.isfinite(expected)
            except OverflowError:
                valid_version = False
            if (
                not isinstance(key, str)
                or not re.fullmatch(JOB_ID_PATTERN, key)
                or key in seen
                or not valid_version
            ):
                raise Failure(CODE_INVALID_CANCEL_BATCH)
            seen.add(key)
            values.append((key, expected))
        cancelled: list[str] = []
        already: list[str] = []
        skipped: list[dict[str, object]] = []
        with self.store.db() as c:
            c.execute(
                "CREATE TEMP TABLE cancel_batch_input(id TEXT PRIMARY KEY,expected REAL NOT NULL)"
            )
            c.executemany("INSERT INTO cancel_batch_input VALUES(?,?)", values)
            rows = c.execute(
                """SELECT i.id,i.expected,j.id AS found,j.state,j.updated,j.intent,j.issue,
                json_extract(j.result,'$.primary_publication') AS primary_receipt,
                EXISTS(SELECT 1 FROM workflow_wait_owner o WHERE o.job_id=j.id
                  AND o.phase IN ('ready','waiting','running','complete')) AS owned,
                EXISTS(SELECT 1 FROM queue_operator_actions a WHERE a.job_id=j.id
                  AND a.action='cancel') AS audited
                FROM cancel_batch_input i LEFT JOIN jobs j ON j.id=i.id"""
            ).fetchall()
            for row in rows:
                code = None
                if row["found"] is None:
                    code = CODE_JOB_NOT_FOUND
                elif row["state"] == "cancelled" and row["audited"]:
                    already.append(row["id"])
                    continue
                elif row["updated"] != row["expected"]:
                    code = CODE_ITEM_CHANGED
                elif (
                    row["state"] not in ("queued", "retry")
                    or row["owned"]
                    or row["intent"] is not None
                    or row["primary_receipt"] is not None
                    or row["issue"]
                ):
                    code = CODE_NOT_CANCELLABLE
                if code:
                    skipped.append({"job_id": row["id"], "code": code})
                else:
                    cancelled.append(row["id"])
            c.execute("CREATE TEMP TABLE cancel_batch_eligible(id TEXT PRIMARY KEY)")
            c.executemany(
                "INSERT INTO cancel_batch_eligible VALUES(?)", ((key,) for key in cancelled)
            )
            now = time.time()
            c.execute(
                """INSERT INTO queue_operator_actions(
                job_id,action,at,previous_state,previous_error,previous_updated,source)
                SELECT j.id,'cancel',?,j.state,j.error,j.updated,'private-sso-queue-ui'
                FROM jobs j JOIN cancel_batch_eligible e ON e.id=j.id""",
                (now,),
            )
            c.execute(
                """UPDATE jobs SET state='cancelled',lease=0,updated=?,error='OPERATOR_CANCELLED'
                WHERE id IN (SELECT id FROM cancel_batch_eligible)""",
                (now,),
            )
            counts = {
                r["state"]: r["n"]
                for r in c.execute("SELECT state,count(*) n FROM jobs GROUP BY state")
            }
        return {
            "cancelled": cancelled,
            "already_cancelled": already,
            "skipped": skipped,
            "counts": counts,
            "now": now,
        }

    def cancel(self, data: Mapping[str, object]) -> dict[str, object]:
        """Atomically move one fresh queued/retry job into the cancelled state."""
        key = data.get("job_id")
        expected = data.get("expected_updated")
        if (
            not isinstance(key, str)
            or not re.fullmatch(JOB_ID_PATTERN, key)
            or type(expected) not in (int, float)
            or not math.isfinite(cast("float", expected))
        ):
            raise Failure(CODE_INVALID_CANCEL)
        with self.store.db() as c:
            row = c.execute(
                """SELECT j.state,j.updated,j.intent,j.issue,j.error,
                json_extract(j.result,'$.primary_publication') AS primary_receipt,
                EXISTS(SELECT 1 FROM workflow_wait_owner o WHERE o.job_id=j.id
                  AND o.phase IN ('ready','waiting','running','complete')) AS owned
                FROM jobs j WHERE j.id=?""",
                (key,),
            ).fetchone()
            if row is None:
                raise Failure(CODE_JOB_NOT_FOUND)
            if (
                row["state"] == "cancelled"
                and c.execute(
                    "SELECT 1 FROM queue_operator_actions WHERE job_id=? AND action='cancel'",
                    (key,),
                ).fetchone()
            ):
                return {"status": "cancelled", "already_applied": True}
            if row["updated"] != expected:
                raise Failure(CODE_ITEM_CHANGED)
            if (
                row["state"] not in ("queued", "retry")
                or row["owned"]
                or row["intent"] is not None
                or row["primary_receipt"] is not None
                or row["issue"]
            ):
                raise Failure(CODE_NOT_CANCELLABLE)
            now = time.time()
            c.execute(
                "UPDATE jobs SET state='cancelled',lease=0,updated=?,"
                "error='OPERATOR_CANCELLED' WHERE id=?",
                (now, key),
            )
            c.execute(
                "INSERT INTO queue_operator_actions(job_id,action,at,previous_state,previous_error,"
                "previous_updated,source) VALUES(?,'cancel',?,?,?,?,'private-sso-queue-ui')",
                (key, now, row["state"], row["error"], row["updated"]),
            )
        return {"status": "cancelled", "already_applied": False}
