"""Durable opt-in v1 stage admission and execution ownership.

Legacy routes never return patient success. Mutations use Store's immediate
transactions; expired running owners require review unless their stage checkpoint
already committed. Waiting owners have no in-flight side effect to replay.
"""

from __future__ import annotations

import json
import math
import re
import secrets
from typing import TYPE_CHECKING

from core import Failure

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from core import Store

ABSOLUTE_SECONDS = 21600
INFLIGHT_SECONDS = 1980
WAIT_GRACE_SECONDS = 180
MIN_DURABLE_WAIT_SECONDS = 66
MAX_EXECUTION_ID_LENGTH = 32
MAX_REVISION_LENGTH = 128
MAX_RETRY_AFTER_SECONDS = 86400
EMPTY_CLAIM: dict[str, object] = {"status": "empty", "job_id": "", "contract": 1}
REVISION = "durable-v1"
STAGES = ("match", "collect", "analyze", "publish")


class WaitOwners:
    """Durable workflow-owner ledger mounted on one Store instance."""

    def __init__(self, store: Store) -> None:
        """Create the owner, tombstone and empty-claim tables on the store."""
        self.store = store
        with store.db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS workflow_wait_owner (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id),
                execution_id TEXT UNIQUE NOT NULL, revision TEXT NOT NULL,
                fence TEXT NOT NULL, stage TEXT NOT NULL,
                phase TEXT NOT NULL, due REAL NOT NULL, expires REAL NOT NULL,
                deadline REAL NOT NULL, request_fence TEXT, response TEXT, request_stage TEXT)""")

            c.execute(
                "CREATE TABLE IF NOT EXISTS workflow_execution_tombstone "
                "(execution_id TEXT PRIMARY KEY)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS workflow_empty_claim "
                "(execution_id TEXT PRIMARY KEY,revision TEXT NOT NULL)"
            )

    @staticmethod
    def _time(now: object) -> None:
        """Refuse any wake timestamp that is not a finite real number."""
        if isinstance(now, bool) or not isinstance(now, float | int) or not math.isfinite(now):
            msg = "INVALID_WAIT_TIME"
            raise Failure(msg)

    def bind(
        self,
        job_id: object,
        execution_id: object,
        revision: object,
        stage: object,
        now: float,
    ) -> dict[str, object]:
        """Bind one execution identity to a processing job or return its owner."""
        self._time(now)
        if (
            stage not in STAGES
            or not isinstance(execution_id, str)
            or not execution_id.isdecimal()
            or len(execution_id) > MAX_EXECUTION_ID_LENGTH
            or not isinstance(revision, str)
            or not 1 <= len(revision) <= MAX_REVISION_LENGTH
        ):
            msg = "INVALID_WAIT_OWNER"
            raise Failure(msg)
        with self.store.db() as c:
            row = c.execute(
                "SELECT * FROM workflow_wait_owner WHERE execution_id=? OR job_id=?",
                (execution_id, job_id),
            ).fetchone()
            if row:
                if (row["job_id"], row["execution_id"], row["revision"]) != (
                    job_id,
                    execution_id,
                    revision,
                ):
                    msg = "WAIT_OWNER_CONFLICT"
                    raise Failure(msg)
                if row["expires"] <= now:
                    msg = "WAIT_OWNER_EXPIRED"
                    raise Failure(msg)
                owner: dict[str, object] = dict(row)
                return owner
            job = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job["state"] != "processing" or job["stage"] != STAGES.index(stage):
                msg = "INVALID_STAGE_ORDER"
                raise Failure(msg)
            c.execute(
                "INSERT INTO "
                "workflow_wait_owner(job_id,execution_id,revision,fence,stage,phase,due,expires,"
                "deadline) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    execution_id,
                    revision,
                    secrets.token_hex(32),
                    stage,
                    "running",
                    now,
                    now + INFLIGHT_SECONDS,
                    now + ABSOLUTE_SECONDS,
                ),
            )
            fresh: dict[str, object] = dict(
                c.execute("SELECT * FROM workflow_wait_owner WHERE job_id=?", (job_id,)).fetchone()
            )
            return fresh

    def _checked(self, c: sqlite3.Connection, owner: dict[str, object], now: float) -> sqlite3.Row:
        """Re-read the owner row and refuse stale, expired or reordered owners."""
        row: sqlite3.Row | None = c.execute(
            "SELECT * FROM workflow_wait_owner WHERE job_id=?", (owner.get("job_id"),)
        ).fetchone()
        if not row or any(
            row[k] != owner.get(k) for k in ("execution_id", "revision", "fence", "stage")
        ):
            msg = "STALE_WAIT_OWNER"
            raise Failure(msg)
        if now >= min(row["expires"], row["deadline"]):
            msg = "WAIT_OWNER_EXPIRED"
            raise Failure(msg)
        job = c.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
        if not job or job["stage"] != STAGES.index(row["stage"]) or job["state"] != "processing":
            msg = "INVALID_STAGE_ORDER"
            raise Failure(msg)
        return row

    def defer(
        self, owner: dict[str, object], code: object, retry_after: float, now: float
    ) -> dict[str, object]:
        """Admit one bounded LLM deferral on a live owner, or keep the old wait."""
        self._time(now)
        if code != "LLM_ADMISSION_DEFERRED":
            msg = "UNSAFE_WAIT_ERROR"
            raise Failure(msg)
        if (
            type(retry_after) not in (float, int)
            or not math.isfinite(retry_after)
            or not 0 <= retry_after <= MAX_RETRY_AFTER_SECONDS
        ):
            msg = "INVALID_WAIT_TIME"
            raise Failure(msg)
        with self.store.db() as c:
            row = self._checked(c, owner, now)
            if row["phase"] == "waiting":
                waiting: dict[str, object] = dict(row)
                return waiting  # Lost HTTP response cannot extend the wait.
            due = now + max(MIN_DURABLE_WAIT_SECONDS, retry_after + 2)
            if due + WAIT_GRACE_SECONDS >= row["deadline"]:
                msg = "WAIT_DEADLINE_EXCEEDED"
                raise Failure(msg)
            c.execute(
                "UPDATE workflow_wait_owner SET phase='waiting',due=?,expires=? WHERE job_id=?",
                (due, due + WAIT_GRACE_SECONDS, row["job_id"]),
            )
            deferred: dict[str, object] = dict(
                c.execute(
                    "SELECT * FROM workflow_wait_owner WHERE job_id=?", (row["job_id"],)
                ).fetchone()
            )
            return deferred

    def resume(self, owner: dict[str, object], now: float) -> dict[str, object]:
        """Consume a due wake exactly once, rotating the owner fence."""
        self._time(now)
        with self.store.db() as c:
            row = self._checked(c, owner, now)
            if row["phase"] != "waiting":
                # A duplicated resume must not authorize another model request.
                msg = "WAIT_RESUME_ALREADY_CONSUMED"
                raise Failure(msg)
            if now < row["due"]:
                msg = "WAIT_NOT_DUE"
                raise Failure(msg)
            # Rotate on consuming wake; late duplicates carry an obsolete fence.
            c.execute(
                "UPDATE workflow_wait_owner SET phase='running',fence=?,expires=? WHERE job_id=?",
                (
                    secrets.token_hex(32),
                    min(now + INFLIGHT_SECONDS, row["deadline"]),
                    row["job_id"],
                ),
            )
            resumed: dict[str, object] = dict(
                c.execute(
                    "SELECT * FROM workflow_wait_owner WHERE job_id=?", (row["job_id"],)
                ).fetchone()
            )
            return resumed

    @staticmethod
    def validate_identity(execution_id: object, revision: object) -> None:
        """Require the reviewed decimal execution identity and revision."""
        if (
            not isinstance(execution_id, str)
            or not re.fullmatch(r"[1-9][0-9]{0,31}", execution_id)
            or revision != REVISION
        ):
            msg = "INVALID_WAIT_OWNER"
            raise Failure(msg)

    def _claim_replay(self, old: sqlite3.Row, revision: object) -> dict[str, object]:
        """Answer a replayed wake from its committed owner state."""
        if old["revision"] != revision or old["phase"] in ("revoked", "failed"):
            msg = "STALE_WAIT_OWNER"
            raise Failure(msg)
        if old["phase"] == "running":
            msg = "WAIT_REQUEST_IN_FLIGHT"
            raise Failure(msg)
        if old["phase"] == "complete":
            replayed: dict[str, object] = json.loads(old["response"])
            return replayed
        envelope: dict[str, object] = self.envelope(
            dict(old), "deferred" if old["phase"] == "waiting" else "ready"
        )
        return envelope

    def _claim_fresh(
        self,
        c: sqlite3.Connection,
        execution_id: object,
        revision: object,
        now: float,
    ) -> dict[str, object]:
        """Claim the next runnable job for a fresh wake, or record an empty claim."""
        # A fresh callback acknowledges its wake just like legacy claim().
        # Replayed execution/empty claims above must not clear a newer wake.
        c.execute("DELETE FROM dispatch WHERE singleton=1")
        if c.execute("SELECT 1 FROM jobs WHERE state='processing' AND lease>?", (now,)).fetchone():
            c.execute("INSERT INTO workflow_empty_claim VALUES(?,?)", (execution_id, revision))
            return dict(EMPTY_CLAIM)
        row, _ = self.store.schedule(c, now)
        if not row:
            c.execute("INSERT INTO workflow_empty_claim VALUES(?,?)", (execution_id, revision))
            return dict(EMPTY_CLAIM)
        if row["stage"] >= len(STAGES):
            # Publish already finished. Leaving stage 4 queued makes claim
            # sort this row first and IndexError, which 500s every wake.
            c.execute(
                "UPDATE jobs SET state='complete',lease=0,updated=? WHERE id=? AND state IN "
                "('queued','retry')",
                (now, row["id"]),
            )
            c.execute("INSERT INTO workflow_empty_claim VALUES(?,?)", (execution_id, revision))
            return dict(EMPTY_CLAIM)
        c.execute(
            "UPDATE jobs SET state='processing',lease=?,attempts=attempts+1,updated=? WHERE id=?",
            (now + WAIT_GRACE_SECONDS, now, row["id"]),
        )
        c.execute(
            "DELETE FROM workflow_wait_owner WHERE job_id=? AND phase IN ('failed','revoked')",
            (row["id"],),
        )
        stage = STAGES[row["stage"]]
        c.execute(
            "INSERT INTO "
            "workflow_wait_owner(job_id,execution_id,revision,fence,stage,phase,due,expires,"
            "deadline) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                row["id"],
                execution_id,
                revision,
                secrets.token_hex(32),
                stage,
                "ready",
                now,
                now + WAIT_GRACE_SECONDS,
                now + ABSOLUTE_SECONDS,
            ),
        )
        claimed: dict[str, object] = self.envelope(
            dict(
                c.execute(
                    "SELECT * FROM workflow_wait_owner WHERE job_id=?", (row["id"],)
                ).fetchone()
            )
        )
        return claimed

    def claim(self, execution_id: object, revision: object, now: float) -> dict[str, object]:
        """Answer one workflow callback: replay, resume or fresh claim."""
        self.validate_identity(execution_id, revision)
        with self.store.db() as c:
            self.store.reconcile_owners(c, now)
            empty = c.execute(
                "SELECT revision FROM workflow_empty_claim WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if empty:
                if empty["revision"] != revision:
                    msg = "STALE_WAIT_OWNER"
                    raise Failure(msg)
                return dict(EMPTY_CLAIM)
            if c.execute(
                "SELECT 1 FROM workflow_execution_tombstone WHERE execution_id=?", (execution_id,)
            ).fetchone():
                msg = "STALE_WAIT_OWNER"
                raise Failure(msg)
            old = c.execute(
                "SELECT * FROM workflow_wait_owner WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if old:
                return self._claim_replay(old, revision)
            return self._claim_fresh(c, execution_id, revision, now)

    @staticmethod
    def envelope(row: dict[str, object], status: object = "ready") -> dict[str, object]:
        """Project an owner row into the wire envelope consumed by the worker."""
        return {
            "contract": 1,
            "status": status,
            "job_id": row["job_id"],
            "execution_id": row["execution_id"],
            "workflow_revision": row["revision"],
            "fence": row["fence"],
            "stage": row["stage"],
            "due_at": row["due"],
            "deadline": row["deadline"],
        }

    def begin(
        self, name: str, data: dict[str, object], now: float
    ) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        """Start one stage under a fresh owner, or replay its committed response."""
        self.validate_identity(data.get("execution_id"), data.get("workflow_revision"))
        with self.store.db() as c:
            row = c.execute(
                "SELECT * FROM workflow_wait_owner WHERE job_id=?", (data.get("job_id"),)
            ).fetchone()
            if not row or any(
                row[k] != data.get(v)
                for k, v in (("execution_id", "execution_id"), ("revision", "workflow_revision"))
            ):
                msg = "STALE_WAIT_OWNER"
                raise Failure(msg)
            if now >= min(row["expires"], row["deadline"]):
                msg = "WAIT_OWNER_EXPIRED"
                raise Failure(msg)
            # Replay an already committed HTTP response, never another model call.
            if row["request_fence"] == data.get("fence") and row["response"]:
                if row["request_stage"] != name or data.get("stage") != name:
                    msg = "STALE_WAIT_OWNER"
                    raise Failure(msg)
                replayed: dict[str, object] = json.loads(row["response"])
                return replayed, None
            if (
                row["fence"] != data.get("fence")
                or row["stage"] != name
                or data.get("stage") != name
                or row["phase"] not in ("ready", "waiting")
            ):
                msg = "STALE_WAIT_OWNER"
                raise Failure(msg)
            if now >= min(row["expires"], row["deadline"]):
                msg = "WAIT_OWNER_EXPIRED"
                raise Failure(msg)
            if row["phase"] == "waiting" and now < row["due"]:
                msg = "WAIT_NOT_DUE"
                raise Failure(msg)
            job = c.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            if not job or job["stage"] != STAGES.index(name) or job["state"] != "processing":
                msg = "INVALID_STAGE_ORDER"
                raise Failure(msg)
            c.execute(
                "UPDATE workflow_wait_owner SET "
                "phase='running',request_fence=?,request_stage=?,response=NULL,expires=? WHERE "
                "job_id=?",
                (row["fence"], name, min(now + INFLIGHT_SECONDS, row["deadline"]), row["job_id"]),
            )
            c.execute(
                "UPDATE jobs SET lease=? WHERE id=?",
                (min(now + INFLIGHT_SECONDS, row["deadline"]), row["job_id"]),
            )
            started: dict[str, object] = dict(row)
            return None, started

    def finish(
        self,
        owner: dict[str, object],
        *,
        deferred: bool,
        now: float,
        retry_after: object = None,
        code: str = "LLM_ADMISSION_DEFERRED",
    ) -> dict[str, object]:
        """Commit the stage outcome (deferral, continuation or completion)."""
        if deferred and code not in {"LLM_ADMISSION_DEFERRED", "GITHUB_READ_TIMEOUT"}:
            msg = "UNSAFE_WAIT_ERROR"
            raise Failure(msg)
        with self.store.db() as c:
            row = c.execute(
                "SELECT * FROM workflow_wait_owner WHERE job_id=?", (owner["job_id"],)
            ).fetchone()
            if not row or row["phase"] != "running" or row["fence"] != owner["fence"]:
                msg = "STALE_WAIT_OWNER"
                raise Failure(msg)
            job = c.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            phase: str
            stage: str
            expires: float
            if deferred:
                if job["stage"] != STAGES.index(row["stage"]):
                    msg = "INVALID_STAGE_ORDER"
                    raise Failure(msg)
                delay = Failure(code, retry_after).retry_after
                due = now + max(MIN_DURABLE_WAIT_SECONDS, (delay or 61) + 2)
                expires = due + WAIT_GRACE_SECONDS
                if expires >= row["deadline"]:
                    msg = "WAIT_DEADLINE_EXCEEDED"
                    raise Failure(msg)
                phase = "waiting"
                stage = str(row["stage"])
                c.execute(
                    "UPDATE jobs SET lease=0,available=?,updated=?,error=? WHERE id=?",
                    (due, now, code, row["job_id"]),
                )
            else:
                if job["stage"] != STAGES.index(row["stage"]) + 1:
                    msg = "INVALID_STAGE_ORDER"
                    raise Failure(msg)
                phase = "complete" if job["stage"] == len(STAGES) else "ready"
                stage = STAGES[min(job["stage"], 3)]
                due = now
                expires = min(now + WAIT_GRACE_SECONDS, row["deadline"])
                if phase == "ready":
                    c.execute(
                        "UPDATE jobs SET lease=?,updated=? WHERE id=?",
                        (expires, now, row["job_id"]),
                    )
            fence = secrets.token_hex(32)
            response: dict[str, object] = self.envelope(
                dict(row) | {"fence": fence, "stage": stage, "due": due},
                "deferred" if deferred else ("complete" if phase == "complete" else "ready"),
            )
            if deferred:
                response["code"] = code
            if phase == "complete":
                response["outcome"] = job["state"]
            c.execute(
                "UPDATE workflow_wait_owner SET "
                "phase=?,stage=?,fence=?,due=?,expires=?,response=? WHERE job_id=?",
                (phase, stage, fence, due, expires, json.dumps(response), row["job_id"]),
            )
            return response

    def snapshot_replaced(self, c: sqlite3.Connection, key: str, now: float) -> None:
        """Commit a safe rewind receipt with Store.replace_snapshot's job reset.

        Legacy calls have no running v1 owner. Never mint a new claim, deadline,
        budget, or authority to replay an ambiguous publication.
        """
        from core import OWNER_CONTEXT

        row = c.execute("SELECT * FROM workflow_wait_owner WHERE job_id=?", (key,)).fetchone()
        if not row or row["phase"] not in ("ready", "waiting", "running"):
            return
        if (
            row["phase"] != "running"
            or getattr(OWNER_CONTEXT, "binding", None) != (key, row["fence"])
            or row["stage"] not in ("collect", "analyze", "publish")
            or row["request_stage"] != row["stage"]
            or row["request_fence"] != row["fence"]
        ):
            msg = "STALE_WAIT_OWNER"
            raise Failure(msg)
        if now >= min(row["expires"], row["deadline"]):
            msg = "WAIT_OWNER_EXPIRED"
            raise Failure(msg)
        job = c.execute("SELECT stage,state,intent FROM jobs WHERE id=?", (key,)).fetchone()
        if job["stage"] != 0 or job["state"] != "processing" or job["intent"]:
            msg = "INVALID_STAGE_ORDER"
            raise Failure(msg)
        fence = secrets.token_hex(32)
        expires = min(now + WAIT_GRACE_SECONDS, row["deadline"])
        response: dict[str, object] = self.envelope(
            dict(row) | {"fence": fence, "stage": "match", "due": now}, "ready"
        )
        c.execute(
            "UPDATE workflow_wait_owner SET "
            "phase='ready',stage='match',fence=?,due=?,expires=?,response=? WHERE job_id=?",
            (fence, now, expires, json.dumps(response), key),
        )
        c.execute("UPDATE jobs SET lease=?,updated=? WHERE id=?", (expires, now, key))

    def snapshot_response(self, owner: dict[str, object], now: float) -> dict[str, object] | None:
        """Only the exact committed old request may receive its rewind receipt."""
        with self.store.db() as c:
            row = c.execute(
                "SELECT * FROM workflow_wait_owner WHERE job_id=?", (owner["job_id"],)
            ).fetchone()
            if (
                not row
                or row["phase"] != "ready"
                or row["stage"] != "match"
                or row["execution_id"] != owner["execution_id"]
                or row["revision"] != owner["revision"]
                or row["request_fence"] != owner["fence"]
                or row["request_stage"] != owner["stage"]
                or not row["response"]
                or now >= min(row["expires"], row["deadline"])
            ):
                return None
            job = c.execute(
                "SELECT stage,state,intent FROM jobs WHERE id=?", (owner["job_id"],)
            ).fetchone()
            if job["stage"] != 0 or job["state"] != "processing" or job["intent"]:
                return None
            response: dict[str, object] = json.loads(row["response"])
            if (
                response.get("status") != "ready"
                or response.get("stage") != "match"
                or response.get("fence") != row["fence"]
            ):
                msg = "STALE_WAIT_OWNER"
                raise Failure(msg)
            return response

    def failure_callback(self, owner: dict[str, object]) -> Callable[[sqlite3.Connection], None]:
        """Return the on_fail hook that tombstones this execution and fence."""

        def release(c: sqlite3.Connection) -> None:
            c.execute(
                "INSERT OR IGNORE INTO workflow_execution_tombstone VALUES(?)",
                (owner["execution_id"],),
            )
            c.execute(
                "UPDATE workflow_wait_owner SET phase='failed',expires=0 WHERE job_id=? AND "
                "fence=?",
                (owner["job_id"], owner["fence"]),
            )

        return release

    def abandon(self, owner: dict[str, object]) -> None:
        """Fail the owner and keep its execution tombstone against reclaims."""
        # Keep execution tombstone so repeated claim cannot accidentally take a new job.
        with self.store.db() as c:
            c.execute(
                "INSERT OR IGNORE INTO workflow_execution_tombstone VALUES(?)",
                (owner["execution_id"],),
            )
            c.execute(
                "UPDATE workflow_wait_owner SET phase='failed',expires=0 WHERE job_id=? AND "
                "fence=?",
                (owner["job_id"], owner["fence"]),
            )

    def capacity_defer(
        self,
        name: str,
        data: dict[str, object],
        now: float,
        *,
        priority_only: bool = False,
    ) -> dict[str, object] | None:
        """Renew a busy owner with a capacity deferral receipt, or replay one."""
        # Called only when Engine's nonblocking acquisition proved capacity busy.
        # No model/publication is started; renewal and replay receipt commit together.
        self.validate_identity(data.get("execution_id"), data.get("workflow_revision"))
        with self.store.db() as c:
            row = c.execute(
                "SELECT * FROM workflow_wait_owner WHERE job_id=?", (data.get("job_id"),)
            ).fetchone()
            if (
                not row
                or row["execution_id"] != data["execution_id"]
                or row["revision"] != data["workflow_revision"]
            ):
                msg = "STALE_WAIT_OWNER"
                raise Failure(msg)
            if now >= min(row["expires"], row["deadline"]):
                msg = "WAIT_OWNER_EXPIRED"
                raise Failure(msg)
            if row["request_fence"] == data.get("fence") and row["response"]:
                if row["request_stage"] != name or data.get("stage") != name:
                    msg = "STALE_WAIT_OWNER"
                    raise Failure(msg)
                replayed: dict[str, object] = json.loads(row["response"])
                return replayed
            if (
                row["phase"] not in ("ready", "waiting")
                or row["stage"] != name
                or data.get("stage") != name
                or row["fence"] != data.get("fence")
            ):
                msg = "STALE_WAIT_OWNER"
                raise Failure(msg)
            if row["phase"] == "waiting" and now < row["due"]:
                msg = "WAIT_NOT_DUE"
                raise Failure(msg)
            job = c.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            if not job or job["stage"] != STAGES.index(name) or job["state"] != "processing":
                msg = "INVALID_STAGE_ORDER"
                raise Failure(msg)
            self.store.reconcile_owners(c, now)
            if priority_only and not self.store.owned_priority_until(
                c, STAGES.index(name), now, row["job_id"]
            ):
                return None
            due = now + MIN_DURABLE_WAIT_SECONDS + 1 + secrets.randbelow(3)
            if due + WAIT_GRACE_SECONDS >= row["deadline"]:
                msg = "WAIT_DEADLINE_EXCEEDED"
                raise Failure(msg)
            response: dict[str, object] = self.envelope(
                dict(row) | {"fence": secrets.token_hex(32), "due": due}, "deferred"
            )
            response["code"] = "WORKER_ADMISSION_DEFERRED"
            c.execute(
                "UPDATE workflow_wait_owner SET "
                "phase='waiting',fence=?,request_fence=?,request_stage=?,due=?,expires=?,"
                "response=? WHERE job_id=?",
                (
                    response["fence"],
                    row["fence"],
                    name,
                    due,
                    due + WAIT_GRACE_SECONDS,
                    json.dumps(response),
                    row["job_id"],
                ),
            )
            c.execute(
                "UPDATE jobs SET lease=0,available=?,updated=?,error='WORKER_ADMISSION_DEFERRED' "
                "WHERE id=?",
                (due, now, row["job_id"]),
            )
            return response
