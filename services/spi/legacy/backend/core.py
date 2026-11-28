"""Durable SPI jobs and deliberately small, English-only publication contracts."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from durable_wait import WaitOwners

MAX_RETRY_AFTER_SECONDS = 86400
RATE_METADATA_MAX = 1e12
MAX_SCHEMA_KEYS = 64
MAX_LABEL_VALUE = 1024
MAX_ANNOTATION_VALUE = 16000
MAX_FINGERPRINT = 256
MAX_SCHEMA_ARRAY_ITEMS = 30
MAX_SCHEMA_STRING = 8000
ASCII_MAX_CODEPOINT = 127
MAX_TITLE_LENGTH = 180
SNAPSHOT_REPLACEMENT_BUDGET = 2
MAX_RESERVATIONS = 3
MAX_FAILURES = 8
LEGACY_INFLIGHT_SECONDS = 1980
EXPIRY_TAIL_SECONDS = 61
RETRY_AFTER_FALLBACK_SECONDS = 61
STAGE_INDEX = {"match": 0, "collect": 1, "analyze": 2, "publish": 3}

OWNER_CONTEXT = threading.local()


class Failure(Exception):
    """Only fixed, non-sensitive codes may cross the worker API boundary."""

    def __init__(
        self,
        code: str,
        retry_after: object = None,
        rate_metadata: dict[str, object] | None = None,
    ) -> None:
        """Clamp reviewed retry hints and keep only fixed rate metadata keys."""
        if (
            isinstance(retry_after, float | int)
            and not isinstance(retry_after, bool)
            and math.isfinite(retry_after)
        ):
            self.retry_after: float | None = min(
                MAX_RETRY_AFTER_SECONDS, max(0, float(retry_after))
            )
        else:
            self.retry_after = None
        self.rate_metadata: dict[str, object] = {
            k: v
            for k, v in (rate_metadata or {}).items()
            if k
            in {
                "tokens_remaining",
                "tokens_reset",
                "requests_remaining",
                "requests_reset",
                "retry_after",
            }
            and isinstance(v, float | int)
            and not isinstance(v, bool)
            and math.isfinite(v)
            and 0 <= v <= RATE_METADATA_MAX
        }
        self.code = code
        super().__init__(code)


# Only explicitly classified safe-to-repeat failures escape the terminal budget.
# GitHub publication ambiguity must NEVER acquire this classification.
LLM_TRANSIENT = {
    "LLM_" + code
    for code in (
        "HTTP_408",
        "HTTP_425",
        "HTTP_429",
        "HTTP_500",
        "HTTP_502",
        "HTTP_503",
        "HTTP_504",
        "UPSTREAM_TIMEOUT",
        "UPSTREAM_NETWORK_ERROR",
        "REQUEST_BUDGET_EXCEEDED",
        "MODEL_STAGE_BUDGET_EXCEEDED",
        "ADMISSION_DEFERRED",
    )
}

PATIENT_TRANSIENT = LLM_TRANSIENT | {
    "STORAGE_TRANSIENT",
    "GITHUB_SNAPSHOT_UNSTABLE",
    "GITHUB_READ_TIMEOUT",
}

SECRET_KEY = re.compile(
    r"authorization|cookie|password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token"
    r"|x[_-]?token|private[_-]?key",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}"
    r"|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|-----BEGIN[^\n]*PRIVATE KEY-----[\s\S]*?-----END[^\n]*PRIVATE KEY-----)"
)
ASSIGNMENT = re.compile(
    r"(?i)((?:password|passwd|secret|token|api[_-]?key|cookie|authorization)\s*[=:]\s*)[^\s,;&]+"
)


def clean(value: object) -> object:
    """Return a redacted copy of arbitrary webhook-derived JSON."""
    if isinstance(value, dict):
        return {
            str(k)[:128]: "[REDACTED]" if SECRET_KEY.search(str(k)) else clean(v)
            for k, v in list(value.items())[:100]
        }
    if isinstance(value, list):
        return [clean(v) for v in value[:500]]
    if isinstance(value, str):
        return ASSIGNMENT.sub(r"\1[REDACTED]", SECRET_VALUE.sub("[REDACTED]", value))[
            :12000
        ]
    return value


def digest(value: object) -> str:
    """Hash one canonical JSON value into the stable episode/event identity."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def timestamp(text: object) -> str:
    """Canonicalize one alert timestamp to UTC ISO-8601 'Z' form."""
    if not isinstance(text, str):
        msg = "INVALID_ALERT_TIMESTAMP"
        raise Failure(msg)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        msg = "INVALID_ALERT_TIMESTAMP"
        raise Failure(msg) from None
    if not parsed.tzinfo:
        msg = "INVALID_ALERT_TIMESTAMP"
        raise Failure(msg)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize(payload: object) -> dict[str, object]:
    """Validate and canonicalize one webhook payload into a job event."""
    if not isinstance(payload, dict) or not isinstance(payload.get("alert"), dict):
        msg = "INVALID_ALERT"
        raise Failure(msg)
    raw = payload["alert"]
    if raw.get("status") not in ("firing", "resolved"):
        msg = "INVALID_ALERT_STATUS"
        raise Failure(msg)
    labels = raw.get("labels", {})
    if (
        not isinstance(labels, dict)
        or not labels.get("alertname")
        or len(labels) > MAX_SCHEMA_KEYS
    ):
        msg = "INVALID_ALERT_LABELS"
        raise Failure(msg)
    if any(
        not isinstance(k, str) or not isinstance(v, str) or len(v) > MAX_LABEL_VALUE
        for k, v in labels.items()
    ):
        msg = "INVALID_ALERT_LABELS"
        raise Failure(msg)
    annotations = raw.get("annotations", {})
    if (
        not isinstance(annotations, dict)
        or len(annotations) > MAX_SCHEMA_KEYS
        or any(
            not isinstance(v, str) or len(v) > MAX_ANNOTATION_VALUE
            for v in annotations.values()
        )
    ):
        msg = "INVALID_ALERT_ANNOTATIONS"
        raise Failure(msg)
    if (
        not isinstance(raw.get("fingerprint", ""), str)
        or len(raw.get("fingerprint", "")) > MAX_FINGERPRINT
    ):
        msg = "INVALID_ALERT_FINGERPRINT"
        raise Failure(msg)
    started = timestamp(raw.get("startsAt"))
    source = str(payload.get("source", "socrat-alerts"))[:256]
    episode = digest([source, raw.get("fingerprint") or digest(labels), started])
    cleaned = clean(
        {
            "source": source,
            "status": raw["status"],
            "labels": labels,
            "annotations": raw.get("annotations", {}),
            "startsAt": started,
            "endsAt": timestamp(raw["endsAt"])
            if raw.get("endsAt") and not raw["endsAt"].startswith("0001-")
            else None,
            "generatorURL": raw.get("generatorURL", ""),
        }
    )
    if not isinstance(cleaned, dict):
        msg = "INVALID_ALERT"
        raise Failure(msg)
    result: dict[str, object] = cleaned
    # Episode identity is computed before redaction, but contains no reversible payload.
    result["episode"] = episode
    result["event_key"] = digest([episode, raw["status"]])
    return result


MATCH_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issue_number", "reason", "confidence"],
    "properties": {
        "issue_number": {"type": "integer", "minimum": 0},
        "reason": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}
REPORT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low", "unknown"],
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "issue_number": {"type": "integer", "minimum": 0},
        "match_reason": {"type": "string"},
        "impact": {"type": "string"},
        "facts": {"type": "array", "items": {"type": "string"}},
        "hypotheses": {"type": "array", "items": {"type": "string"}},
        "alert_quality": {
            "type": "string",
            "enum": [
                "actionable",
                "likely_noisy",
                "duplicate",
                "insufficient_evidence",
            ],
        },
        "alert_assessment": {"type": "string"},
        "service_actions": {"type": "array", "items": {"type": "string"}},
        "monitoring_actions": {"type": "array", "items": {"type": "string"}},
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
    },
}
_report_properties = REPORT_SCHEMA["properties"]
if isinstance(_report_properties, dict):
    REPORT_SCHEMA["required"] = list(_report_properties)


def _validate_object(value: object, schema: dict[str, object]) -> None:
    properties = schema["properties"]
    required = schema["required"]
    if (
        not isinstance(value, dict)
        or not isinstance(properties, dict)
        or not isinstance(required, list)
        or set(value) != set(required)
    ):
        msg = "INVALID_MODEL_SCHEMA"
        raise Failure(msg)
    for name, expected in properties.items():
        validate(value[name], expected)


def _validate_array(value: object, schema: dict[str, object]) -> None:
    items = schema["items"]
    if not isinstance(value, list) or len(value) > MAX_SCHEMA_ARRAY_ITEMS:
        msg = "INVALID_MODEL_SCHEMA"
        raise Failure(msg)
    if not isinstance(items, dict):
        msg = "INVALID_MODEL_SCHEMA"
        raise Failure(msg)
    for entry in value:
        validate(entry, items)


def _validate_string(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_SCHEMA_STRING
    ):
        msg = "INVALID_MODEL_SCHEMA"
        raise Failure(msg)
    # Fail closed on non-English scripts rather than publishing untranslated prose.
    if any(ord(c) > ASCII_MAX_CODEPOINT and c.isalpha() for c in value):
        msg = "NON_ENGLISH_MODEL_OUTPUT"
        raise Failure(msg)


def _validate_integer(value: object, schema: dict[str, object]) -> None:
    minimum = schema.get("minimum", 0)
    if type(value) is not int or value < (minimum if isinstance(minimum, int) else 0):
        msg = "INVALID_MODEL_SCHEMA"
        raise Failure(msg)


def validate(value: object, schema: dict[str, object]) -> object:
    """Small strict validator for the intentionally restricted schemas above."""
    typ = schema["type"]
    if typ == "object":
        _validate_object(value, schema)
    elif typ == "array":
        _validate_array(value, schema)
    elif typ == "string":
        _validate_string(value)
    elif typ == "integer":
        _validate_integer(value, schema)
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        msg = "INVALID_MODEL_SCHEMA"
        raise Failure(msg)
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        msg = "INVALID_MODEL_SCHEMA"
        raise Failure(msg)
    return value


def _lines(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        msg = "INVALID_MODEL_SCHEMA"
        raise Failure(msg)
    return value


def render(report: dict[str, object], event: dict[str, object]) -> tuple[str, str]:
    """Render the validated report into the reviewed issue title and body."""
    validate(report, REPORT_SCHEMA)
    title = _str(report["title"]).strip()
    if not title.startswith("[SPI] "):
        title = "[SPI] " + title
    if len(title) > MAX_TITLE_LENGTH or "\n" in title:
        msg = "INVALID_ISSUE_TITLE"
        raise Failure(msg)
    lines = [
        _str(report["summary"]),
        "",
        f"**Severity:** {report['severity']} · **Confidence:** {report['confidence']}",
        "",
        "## Observed impact",
        _str(report["impact"]),
    ]
    for heading, field in [
        ("Verified facts", "facts"),
        ("Hypotheses (not established root cause)", "hypotheses"),
        ("Service recovery and prevention", "service_actions"),
        ("Monitoring improvements", "monitoring_actions"),
        ("Missing evidence", "missing_evidence"),
    ]:
        lines += ["", "## " + heading] + ["- " + x for x in _lines(report[field])]
    lines += [
        "",
        "## Alert quality",
        "**Classification:** " + _str(report["alert_quality"]),
        _str(report["alert_assessment"]),
        "",
        "## Incident correlation",
        _str(report["match_reason"]),
        "",
        "## Provenance",
        "- Started: " + _str(event["startsAt"]),
        "- Analysis is automated and read-only; recommendations require review.",
        "- Bounded diagnostic artifacts, collection gaps and absolute-time Explore links "
        "accompany this episode when collected.",
        "- Missing series or zero matching errors do not establish service health or exclude an "
        "incident.",
        "- Deployed image IDs and OCI build claims are distinguished from verified source; "
        "repository-main references do not prove deployment.",
        "- Credentials are redacted; diagnostic artifacts may reveal internal topology.",
        "",
        "<!-- socrat-spi:" + _str(event["event_key"]) + " -->",
    ]
    body = "\n".join(lines)
    # Redaction changing model output is a contract failure, not silent publication.
    if clean(title) != title or clean(body) != body:
        msg = "UNSAFE_MODEL_OUTPUT"
        raise Failure(msg)
    return title, body


# Context/work bounds and minute throughput are deliberately independent.
LLM_REQUEST_TOKEN_LIMIT = 30000
LLM_MINUTE_TOKEN_LIMIT = 30000  # Legacy default; opt-in 60000 at reviewed cutover.

# Post-validators run per reviewed field with fixed SQL text; save() routes
# each reviewed field through its exact statement.
FIELD_UPDATES = {
    "state": "UPDATE jobs SET state=? WHERE id=?",
    "issue": "UPDATE jobs SET issue=? WHERE id=?",
    "intent": "UPDATE jobs SET intent=? WHERE id=?",
    "error": "UPDATE jobs SET error=? WHERE id=?",
}

_RETRY_JITTER = random.SystemRandom()


class Store:
    """SQLite-backed durable job ledger with one worker slot per store file."""

    def __init__(
        self, path: object, minute_token_limit: int = LLM_MINUTE_TOKEN_LIMIT
    ) -> None:
        """Open (or create) the store file and mount the durable wait owners."""
        if type(minute_token_limit) is not int or minute_token_limit not in (
            30000,
            60000,
        ):
            msg = "Unsupported minute token limit"
            raise ValueError(msg)
        self.minute_token_limit = minute_token_limit
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("PRAGMA temp_store=MEMORY")
            c.execute("PRAGMA journal_mode=WAL")
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, episode TEXT NOT NULL, event TEXT NOT NULL,
              stage INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'queued',
              created REAL NOT NULL, updated REAL NOT NULL, available REAL NOT NULL,
              lease REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
              deliveries INTEGER NOT NULL DEFAULT 1, result TEXT NOT NULL DEFAULT '{}',
              issue INTEGER NOT NULL DEFAULT 0, intent TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS snapshot_budget (
              job_id TEXT PRIMARY KEY REFERENCES jobs(id),
              replacements INTEGER NOT NULL, retained TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS match_review_v3 (
              job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
              progress TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS analysis_output_budget (
              job_id TEXT NOT NULL REFERENCES jobs(id), input_digest TEXT NOT NULL,
              failures INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job_id,input_digest));
            CREATE TABLE IF NOT EXISTS llm_rate_metadata (
              job_id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS llm_admission (
              id INTEGER PRIMARY KEY, tokens INTEGER NOT NULL,
              expires REAL NOT NULL, active INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS dispatch (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), token TEXT NOT NULL,
              deadline REAL NOT NULL, attempts INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS job_failure_budget (
              job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
              failures INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS runnable ON jobs(state,available,lease);
            CREATE INDEX IF NOT EXISTS episode ON jobs(episode);
            """)
        from durable_wait import WaitOwners

        self.owners: WaitOwners = WaitOwners(self)

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        """Yield one immediate-transaction connection with commit/rollback."""
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA busy_timeout=15000")
            c.execute("PRAGMA temp_store=MEMORY")
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def match_checkpoint(self, key: str) -> dict[str, object] | None:
        """Return the persistent match progress for one job, if recorded."""
        # Separate namespace survives old workers replacing the jobs.result JSON.
        # Older binaries neither read nor reinterpret this table.
        with self.db() as c:
            row = c.execute(
                "SELECT progress FROM match_review_v3 WHERE job_id=?", (key,)
            ).fetchone()
            progress: dict[str, object] | None = (
                json.loads(row["progress"]) if row else None
            )
        return progress

    def snapshot_guard(self, key: str) -> None:
        """Guard that replacing jobs.result cannot erase the separate ledger."""
        with self.db() as c:
            self._guard_owner(c, key)
            row = c.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
            result = json.loads(row["result"])
            budget = c.execute(
                "SELECT * FROM snapshot_budget WHERE job_id=?", (key,)
            ).fetchone()
            invalid = (
                len(result.get("snapshot_audit", [])) > SNAPSHOT_REPLACEMENT_BUDGET
            )
            if budget:
                retained = json.loads(budget["retained"])
                invalid = (
                    invalid
                    or result.get("snapshot_generation") != budget["replacements"]
                    or result.get("snapshot_audit", [])
                    != retained.get("snapshot_audit", [])
                )
            if invalid:
                c.execute(
                    "UPDATE jobs SET state='dead',error='WRITE_NEEDS_REVIEW',lease=0 WHERE id=?",
                    (key,),
                )
        if invalid:
            msg = "WRITE_NEEDS_REVIEW"
            raise Failure(msg)

    def replace_snapshot(
        self,
        key: str,
        expected: dict[str, object],
        retained: dict[str, object],
        *,
        expensive: bool,
    ) -> None:
        """Budget and reset (or terminal preservation) commit together.

        Three generations total: the initial generation plus two replacements.
        A stage-zero replay is fenced without consuming another replacement.
        """
        exhausted = False
        with self.db() as c:
            self._guard_owner(c, key)
            row = c.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
            if row["stage"] == 0:
                return
            if (
                row["result"] != json.dumps(expected["result"])
                or row["stage"] != expected["stage"]
            ):
                msg = "INVALID_STAGE_ORDER"
                raise Failure(msg)
            budget = c.execute(
                "SELECT * FROM snapshot_budget WHERE job_id=?", (key,)
            ).fetchone()
            audits: list[object] = []
            current = expected["result"]
            if isinstance(current, dict):
                audit_value = current.get("snapshot_audit", [])
                if isinstance(audit_value, list):
                    audits = audit_value
            count = budget["replacements"] if budget else len(audits)
            exhausted = expensive and count >= SNAPSHOT_REPLACEMENT_BUDGET
            if exhausted:
                c.execute(
                    "UPDATE jobs SET state='dead',error='WRITE_NEEDS_REVIEW',lease=0 WHERE id=?",
                    (key,),
                )
            else:
                if expensive:
                    count += 1
                    retained["snapshot_generation"] = count
                    c.execute(
                        "INSERT OR REPLACE INTO snapshot_budget VALUES(?,?,?)",
                        (key, count, json.dumps(retained)),
                    )
                now = time.time()
                c.execute(
                    "UPDATE jobs SET stage=0,result=?,state='processing',updated=?,lease=? WHERE "
                    "id=?",
                    (
                        json.dumps(retained),
                        now,
                        self._processing_lease(c, key, now),
                        key,
                    ),
                )
                self.owners.snapshot_replaced(c, key, now)
        if exhausted:
            msg = "WRITE_NEEDS_REVIEW"
            raise Failure(msg)

    def reserve_llm(
        self, tokens: int, timeout: float = 600, now: float | None = None
    ) -> int | None:
        """Admit one bounded token reservation on the shared PVC ledger."""
        if type(tokens) is not int or not 0 < tokens <= LLM_REQUEST_TOKEN_LIMIT:
            msg = "LLM_REQUEST_TOO_LARGE"
            raise Failure(msg)
        now = time.time() if now is None else now
        with self.db() as c:
            binding = getattr(OWNER_CONTEXT, "binding", None)
            if binding:
                self._guard_owner(c, binding[0])
            c.execute("DELETE FROM llm_admission WHERE expires<=?", (now,))
            rows = c.execute("SELECT * FROM llm_admission ORDER BY expires").fetchall()
            if (
                any(r["active"] for r in rows)
                or len(rows) >= MAX_RESERVATIONS
                or sum(r["tokens"] for r in rows) + tokens > self.minute_token_limit
            ):
                # Earliest ledger change; retrying re-evaluates every constraint.
                msg = "LLM_ADMISSION_DEFERRED"
                raise Failure(
                    msg,
                    retry_after=max(1, min(r["expires"] for r in rows) - now),
                )
            reservation: int | None = c.execute(
                "INSERT INTO llm_admission(tokens,expires,active) VALUES(?,?,1)",
                (tokens, now + timeout + EXPIRY_TAIL_SECONDS),
            ).lastrowid
            return reservation

    def finish_llm(
        self, reservation: int, actual: object = None, now: float | None = None
    ) -> None:
        """Settle one reservation; never refund an estimate."""
        now = time.time() if now is None else now
        with self.db() as c:
            # Never refund an estimate: proxy reservation semantics may differ.
            if type(actual) is int and actual >= 0:
                c.execute(
                    "UPDATE llm_admission SET tokens=max(tokens,?) WHERE id=?",
                    (actual, reservation),
                )
            c.execute(
                "UPDATE llm_admission SET active=0,expires=? WHERE id=?",
                (now + EXPIRY_TAIL_SECONDS, reservation),
            )

    def reconcile_owners(self, c: sqlite3.Connection, now: float) -> None:
        """Revoke every expired owner in one reviewed transaction."""
        # No ambiguous paid call is replayed after ownership expires. Waiting
        # owners have no in-flight side effects and may release retained progress.
        rows = c.execute(
            "SELECT * FROM workflow_wait_owner WHERE phase IN ('ready','waiting','running') AND "
            "expires<=?",
            (now,),
        ).fetchall()
        for owner in rows:
            job = c.execute(
                "SELECT stage FROM jobs WHERE id=?", (owner["job_id"],)
            ).fetchone()
            checkpointed = job and job["stage"] > STAGE_INDEX[owner["stage"]]
            if owner["phase"] == "running" and not checkpointed:
                c.execute(
                    "UPDATE jobs SET state='dead',lease=0,error='WRITE_NEEDS_REVIEW' WHERE id=? "
                    "AND state='processing'",
                    (owner["job_id"],),
                )
            else:
                c.execute(
                    "UPDATE jobs SET state='retry',lease=0,available=max(available,?) WHERE id=? "
                    "AND state='processing'",
                    (now, owner["job_id"]),
                )
            c.execute(
                "INSERT OR IGNORE INTO workflow_execution_tombstone VALUES(?)",
                (owner["execution_id"],),
            )
            c.execute(
                "UPDATE workflow_wait_owner SET phase='revoked' WHERE job_id=?",
                (owner["job_id"],),
            )

    def recover_on_start(self) -> int:
        """Reset orphaned processing jobs for the sole replacement worker."""
        # Called only by the sole Recreate worker, never by ordinary connections.
        # The previous process cannot still publish once its replacement starts.
        now = time.time()
        with self.db() as c:
            return c.execute(
                "UPDATE jobs SET state='retry',lease=0,available=?,updated=? WHERE "
                "state='processing' AND id NOT IN (SELECT job_id FROM workflow_wait_owner WHERE "
                "phase IN ('ready','waiting','running'))",
                (now, now),
            ).rowcount

    def enqueue(self, event: dict[str, object]) -> dict[str, object]:
        """Enqueue one event and return its enqueue receipt."""
        return self.enqueue_many([event])[0]

    def enqueue_many(self, events: list[dict[str, object]]) -> list[dict[str, object]]:
        """Enqueue a batch of events inside one transaction."""
        now = time.time()
        with self.db() as c:
            return [self._enqueue(c, event, now) for event in events]

    def _enqueue(
        self, c: sqlite3.Connection, event: dict[str, object], now: float
    ) -> dict[str, object]:
        record: dict[str, object] = {
            "job_id": event["event_key"],
            "duplicate": False,
        }
        key = event["event_key"]
        cur = c.execute(
            "INSERT OR IGNORE INTO jobs(id,episode,event,created,updated,available) "
            "VALUES(?,?,?,?,?,?)",
            (key, event["episode"], json.dumps(event), now, now, now),
        )
        if cur.rowcount == 0:
            c.execute(
                "UPDATE jobs SET deliveries=deliveries+1,updated=? WHERE id=?",
                (now, key),
            )
            record["duplicate"] = True
        return record

    def get(self, key: str) -> dict[str, object]:
        """Return one job with its event and result JSON decoded."""
        with self.db() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        if row is None:
            msg = "JOB_NOT_FOUND"
            raise Failure(msg)
        event_text: str = row["event"]
        result_text: str = row["result"]
        d: dict[str, object] = dict(row)
        d["event"] = json.loads(event_text)
        d["result"] = json.loads(result_text)
        return d

    def owned_priority_until(
        self, c: sqlite3.Connection, stage: int, now: float, exclude: str | None = None
    ) -> float:
        """Return the earliest bounded local owner claiming completion priority."""
        # Only current, bounded local owners can reserve completion priority.
        rows = c.execute(
            """SELECT o.*,j.stage AS durable_stage,j.state AS job_state,
            j.error AS job_error,j.updated AS job_updated FROM workflow_wait_owner o
            JOIN jobs j ON j.id=o.job_id WHERE o.revision='durable-v1'
            AND o.phase IN ('ready','waiting') AND o.expires>? AND o.deadline>?""",
            (now, now),
        ).fetchall()
        current = (
            c.execute(
                "SELECT deadline,job_id FROM workflow_wait_owner WHERE job_id=?",
                (exclude,),
            ).fetchone()
            if exclude
            else None
        )
        until: float = 0
        for owner in rows:
            index = STAGE_INDEX.get(owner["stage"], -1)
            if (
                owner["job_id"] == exclude
                or owner["job_state"] != "processing"
                or owner["durable_stage"] != index
            ):
                continue
            # Drain pre-upgrade cohorts fairly: equal-stage owners retain their
            # original deadline order. Do not let a younger callback steal the
            # slot immediately before an older owner's normal admission wake.
            older = (
                index == stage
                and current is not None
                and (owner["deadline"], owner["job_id"])
                < (current["deadline"], current["job_id"])
            )
            if index < stage or (index == stage and not older):
                continue
            short = (
                index == STAGE_INDEX["analyze"]
                and owner["job_error"] == "LLM_ADMISSION_DEFERRED"
                and owner["due"] <= owner["job_updated"] + 70
            )
            near_wake = older and owner["due"] <= now + 70
            eligible = (
                owner["phase"] == "ready" or owner["due"] <= now or short or near_wake
            )
            bounded = owner["expires"] <= owner["deadline"] and (
                (
                    owner["phase"] == "ready"
                    and owner["expires"] <= owner["job_updated"] + 180
                )
                or (
                    owner["phase"] == "waiting"
                    and owner["expires"] <= owner["due"] + 180
                )
            )
            if eligible and bounded:
                until = max(until, owner["expires"])
        return until

    def schedule(
        self, c: sqlite3.Connection, now: float
    ) -> tuple[sqlite3.Row | None, float | None]:
        """Shared claim/wake policy; never alter durable job deadlines.

        Finish ready work first. A known local analysis admission retry may
        bridge ledger expiry to its jittered due time (at most 664s from failure).
        Unknown provider backoffs never reserve capacity. Expired ledger rows
        are deliberately readable here, but cannot extend the bounded hold.
        """
        self.reconcile_owners(c, now)
        # The worker/model have one execution slot. Waiting releases the HTTP
        # lock and job lease, NOT that logical slot. Starting additional six-hour
        # owners here turns durable Wait into a starvation queue. Keep intake
        # queued until the current owner finishes or is safely reconciled. The
        # same transaction gates v1 claim, legacy claim and dispatcher wakes.
        active = c.execute(
            "SELECT min(min(expires,deadline)) FROM workflow_wait_owner WHERE phase IN "
            "('ready','waiting','running')"
        ).fetchone()[0]
        if active is not None:
            first_deadline: float | None = active
            return None, first_deadline
        rows = c.execute(
            "SELECT id,stage,state,created,updated,available,lease,error FROM jobs WHERE state IN "
            "('queued','retry','processing') AND id NOT IN (SELECT job_id FROM workflow_wait_owner "
            "WHERE phase IN ('ready','waiting','running','complete'))"
        ).fetchall()
        holds = [
            r["available"]
            for r in rows
            if r["state"] == "retry"
            and r["stage"] == STAGE_INDEX["analyze"]
            and r["error"] == "LLM_ADMISSION_DEFERRED"
            and r["lease"] <= now
            and r["updated"] <= now < r["available"] <= r["updated"] + 664
            and c.execute(
                "SELECT 1 FROM llm_admission WHERE expires>=? AND expires<=? AND expires>=? LIMIT "
                "1",
                (r["updated"], r["available"], r["available"] - 4),
            ).fetchone()
        ]
        hold: float = max(holds, default=0)
        scheduled = [
            (
                max(
                    r["available"],
                    r["lease"],
                    hold if r["stage"] == 0 else 0,
                    self.owned_priority_until(c, r["stage"], now),
                ),
                r,
            )
            for r in rows
        ]
        ready = [r for due, r in scheduled if due <= now]
        ready.sort(key=lambda r: (-r["stage"], r["created"], r["id"]))
        deadlines = [due for due, r in scheduled]
        deadlines.extend(
            r[0]
            for r in c.execute(
                "SELECT expires FROM workflow_wait_owner WHERE phase IN "
                "('ready','waiting','running')"
            )
        )
        chosen: sqlite3.Row | None = ready[0] if ready else None
        next_deadline: float | None = min(deadlines, default=None)
        return chosen, next_deadline

    def claim(self) -> dict[str, object]:
        """Claim the next runnable job for the legacy non-durable wake."""
        now = time.time()
        with self.db() as c:
            self.reconcile_owners(c, now)
            c.execute("DELETE FROM dispatch WHERE singleton=1")
            if c.execute(
                "SELECT 1 FROM jobs WHERE state='processing' AND lease>?", (now,)
            ).fetchone():
                receipt: dict[str, object] = {"job_id": ""}
                return receipt
            row, _ = self.schedule(c, now)
            if not row:
                empty: dict[str, object] = {"job_id": ""}
                return empty
            c.execute(
                "UPDATE jobs SET state='processing',lease=?,attempts=attempts+1,updated=? WHERE "
                "id=?",
                (now + LEGACY_INFLIGHT_SECONDS, now, row["id"]),
            )
            claimed: dict[str, object] = {"job_id": row["id"]}
            return claimed

    def _guard_owner(self, c: sqlite3.Connection, key: str) -> None:
        """Refuse writes from stale or expired durable owners."""
        row = c.execute(
            "SELECT fence,phase,expires,deadline FROM workflow_wait_owner WHERE job_id=? AND "
            "phase IN ('ready','waiting','running')",
            (key,),
        ).fetchone()
        if row and time.time() >= min(row["expires"], row["deadline"]):
            msg = "WAIT_OWNER_EXPIRED"
            raise Failure(msg)
        if row and (
            row["phase"] != "running"
            or getattr(OWNER_CONTEXT, "binding", None) != (key, row["fence"])
        ):
            msg = "STALE_WAIT_OWNER"
            raise Failure(msg)

    def _processing_lease(self, c: sqlite3.Connection, key: str, now: float) -> float:
        """Return the lease bound by the live owner's expiry, if any."""
        owner = c.execute(
            "SELECT expires,deadline FROM workflow_wait_owner WHERE job_id=? AND phase IN "
            "('ready','waiting','running')",
            (key,),
        ).fetchone()
        lease: float = (
            min(now + LEGACY_INFLIGHT_SECONDS, owner["expires"], owner["deadline"])
            if owner
            else now + LEGACY_INFLIGHT_SECONDS
        )
        return lease

    def save(
        self,
        key: str,
        stage: int,
        result: dict[str, object],
        on_save: Callable[[sqlite3.Connection], None] | None = None,
        **fields: object,
    ) -> None:
        """Commit one stage checkpoint plus reviewed job fields."""
        allowed = {"state", "issue", "intent", "error"}
        if not set(fields) <= allowed:
            msg = "Invalid job fields"
            raise ValueError(msg)
        now = time.time()
        with self.db() as c:
            self._guard_owner(c, key)
            lease = (
                0
                if fields.get("state") in ("complete", "dry_run", "dead")
                else self._processing_lease(c, key, now)
            )
            c.execute(
                "UPDATE jobs SET stage=?,result=?,updated=?,lease=? WHERE id=?",
                [stage, json.dumps(result), now, lease, key],
            )
            # Each reviewed field carries its own fixed SQL text; the set above
            # is the reviewed whitelist routing into FIELD_UPDATES.
            for name, value in fields.items():
                c.execute(FIELD_UPDATES[name], [value, key])
            if c.execute(
                "SELECT 1 FROM snapshot_budget WHERE job_id=?", (key,)
            ).fetchone():
                # Never overwrite the independent retained copy with an old
                # worker's marker-less reset. Such a reset fails closed later.
                budget = c.execute(
                    "SELECT replacements,retained FROM snapshot_budget WHERE job_id=?",
                    (key,),
                ).fetchone()
                if result.get("snapshot_generation") == budget[
                    "replacements"
                ] and result.get("snapshot_audit", []) == json.loads(
                    budget["retained"]
                ).get("snapshot_audit", []):
                    c.execute(
                        "UPDATE snapshot_budget SET retained=? WHERE job_id=?",
                        (json.dumps(result), key),
                    )
            if on_save is not None:
                on_save(c)

    def fail(
        self,
        key: str,
        code: str,
        retry_after: object = None,
        rate_metadata: dict[str, object] | None = None,
        on_fail: Callable[[sqlite3.Connection], None] | None = None,
    ) -> None:
        """Record one classified failure with its reviewed backoff policy."""
        job = self.get(key)
        now = time.time()
        with self.db() as c:
            self._guard_owner(c, key)
            # Total claims remain diagnostic. Busy LLM deferrals must not spend
            # the independent recovery allowance of later stages/publication.
            if rate_metadata:
                safe = Failure(code, rate_metadata=rate_metadata).rate_metadata
                c.execute(
                    "INSERT OR REPLACE INTO llm_rate_metadata VALUES(?,?)",
                    (key, json.dumps(safe)),
                )
            count: int = cast("int", job["attempts"])
            intent = job["intent"]
            safe_snapshot = (
                code == "OPEN_SPI_CHANGED"
                and job["stage"] == 0
                and (intent is None or intent == "")
            )
            if code not in PATIENT_TRANSIENT and not safe_snapshot:
                c.execute(
                    "INSERT INTO job_failure_budget VALUES(?,1) ON CONFLICT(job_id) DO UPDATE SET "
                    "failures=failures+1",
                    (key,),
                )
                count = c.execute(
                    "SELECT failures FROM job_failure_budget WHERE job_id=?", (key,)
                ).fetchone()[0]
            dead = (
                count >= MAX_FAILURES
                and code not in PATIENT_TRANSIENT
                and not safe_snapshot
            ) or code == "WRITE_NEEDS_REVIEW"
            delay: float = min(
                3600, 30 * 2 ** min(count, 7) * _RETRY_JITTER.uniform(0.8, 1.2)
            )
            if code in PATIENT_TRANSIENT and retry_after is not None:
                delay = max(delay, Failure(code, retry_after).retry_after or 0)
            if code in {
                "LLM_ADMISSION_DEFERRED",
                "GITHUB_SNAPSHOT_UNSTABLE",
                "GITHUB_READ_TIMEOUT",
            } or (code == "LLM_HTTP_429" and retry_after is not None):
                delay = (
                    Failure(code, retry_after).retry_after
                    or RETRY_AFTER_FALLBACK_SECONDS
                ) + _RETRY_JITTER.uniform(1, 3)
            if safe_snapshot:
                delay = 15 + _RETRY_JITTER.uniform(0, 5)
            c.execute(
                "UPDATE jobs SET state=?,lease=0,available=?,updated=?,error=? WHERE id=?",
                ("dead" if dead else "retry", now + delay, now, code, key),
            )
            if on_fail is not None:
                on_fail(c)

    def episode_issue(self, episode: str) -> int:
        """Return the first published issue number of one episode."""
        with self.db() as c:
            row = c.execute(
                "SELECT issue FROM jobs WHERE episode=? AND issue>0 ORDER BY created LIMIT 1",
                (episode,),
            ).fetchone()
            issue: int = row["issue"] if row else 0
        return issue

    def health(self) -> dict[str, object]:
        """Return queue counts and oldest pending age for dashboards."""
        with self.db() as c:
            counts = {
                r["state"]: r["n"]
                for r in c.execute("SELECT state,count(*) n FROM jobs GROUP BY state")
            }
            oldest = c.execute(
                "SELECT min(created) FROM jobs WHERE state IN ('queued','retry','processing')"
            ).fetchone()[0]
            report: dict[str, object] = {
                "counts": counts,
                "oldest_pending_seconds": max(0, int(time.time() - oldest))
                if oldest
                else 0,
            }
        return report

    def reserve_dispatch(
        self, now: float | None = None
    ) -> tuple[str | None, float | None]:
        """Reserve one wake durably; return (reservation id, next deadline)."""
        now = time.time() if now is None else now
        with self.db() as c:
            self.reconcile_owners(c, now)
            active = c.execute(
                "SELECT max(lease) FROM jobs WHERE state='processing' AND lease>?",
                (now,),
            ).fetchone()[0]
            if active:
                busy: float | None = active
                return None, busy
            _, due = self.schedule(c, now)
            if due is None:
                return None, None
            r = c.execute("SELECT * FROM dispatch WHERE singleton=1").fetchone()
            deadline = max(due, r["deadline"] if r else 0)
            if deadline > now:
                upcoming: float | None = deadline
                return None, upcoming
            import uuid

            token = uuid.uuid4().hex
            attempts = (r["attempts"] if r else 0) + 1
            # Both successful and ambiguous responses await callback acknowledgement.
            deadline = now + min(300, 30 * 2 ** min(attempts - 1, 4))
            c.execute(
                "INSERT OR REPLACE INTO dispatch VALUES(1,?,?,?)",
                (token, deadline, attempts),
            )
            reserved: float | None = deadline
            return token, reserved

    def dispatch_status(self) -> dict[str, object]:
        """Return the durable dispatcher wake state for liveness checks."""
        with self.db() as c:
            row = c.execute(
                "SELECT deadline,attempts FROM dispatch WHERE singleton=1"
            ).fetchone()
            status: dict[str, object] = (
                dict(row) if row else {"deadline": 0, "attempts": 0}
            )
            return status
