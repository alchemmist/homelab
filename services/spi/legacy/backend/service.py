"""Authenticated private stage API. Durable state is independent of n8n executions."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Protocol, cast, override

from card_correlation import record_receipt
from core import (
    OWNER_CONTEXT,
    PATIENT_TRANSIENT,
    Failure,
    Store,
    digest,
    normalize,
    render,
)
from dispatcher import Dispatcher
from evidence_bundle import (
    index_markdown,
    publish_parts,
    storage_markdown,
    storage_objects,
)
from grafana_links import repair_markdown_links
from integrations import HTTP, REQUEST_DEADLINE, Evidence, GitHub, Model
from s3_evidence import StorageConflict, StoragePermanent, StorageTransient
from storage_runtime import load_storage
from telegram_delivery import Delivery
from telegram_links import primary_url

if TYPE_CHECKING:
    from collections.abc import Callable
    from email.message import Message
    from io import BufferedReader
    from socket import socket

RUN_DEADLINE_SECONDS = 1800.0
MAX_BODY_BYTES = 512_000
MIN_QUEUE_TOKEN_CHARS = 32
MAX_ALERT_GROUP = 200
JOB_ID_HEX_LENGTH = 64
READ_BODY_TIMEOUT_SECONDS = 10.0
HEARTBEAT_INTERVAL_SECONDS = 60.0
WORKER_PORT = 8080
HTTP_OK = 200
SNAPSHOT_RECHECK_SECONDS = 15
JOB_METRIC_STATES = ("queued", "retry", "processing", "complete", "dry_run", "dead")
LOGGED_PHASE_NAMES = frozenset(
    (
        "match",
        "collect",
        "analyze",
        "publish",
        "sign",
        "installation",
        "mint",
        "publish_secret",
        "bootstrap",
    )
)
LOG_ALLOWED_FIELDS = frozenset(
    (
        "stage",
        "code",
        "phase",
        "recovered_jobs",
        "oldest_pending_seconds",
        "dead_jobs",
        "telegram_links_pending",
    )
)


class GitHubApi(Protocol):
    """Read/write surface of the sealed legacy GitHub adapter."""

    def request(self, method: str, path: str, body: object = None) -> dict[str, object]:
        """Call the GitHub REST surface with the reviewed timeouts."""
        ...

    def snapshot(self) -> list[dict[str, object]]:
        """Return the bounded open-issue snapshot."""
        ...

    def open_signature(self) -> str:
        """Return the digest of the current open-issue snapshot."""
        ...

    def primary_reference(self, marker: str, number: int = 0) -> dict[str, object]:
        """Return the trusted primary publication reference."""
        ...

    def reconcile(self, marker: str, number: int = 0) -> int | None:
        """Return the reconciled open issue number."""
        ...


class ModelApi(Protocol):
    """Model surface; the store backchannel enforces the token budget."""

    store: Store

    def match(
        self,
        event: dict[str, object],
        issues: list[dict[str, object]],
        progress: object = None,
        on_progress: Callable[[object], None] | None = None,
    ) -> dict[str, object]:
        """Run the bounded match pass."""
        ...

    def analyze(
        self, event: dict[str, object], match: object, evidence: object
    ) -> dict[str, object]:
        """Run the bounded analyze pass."""
        ...


class EvidenceApi(Protocol):
    """Evidence collection surface."""

    def collect(self, event: dict[str, object]) -> object:
        """Collect the bounded diagnostic bundle for one event."""
        ...


class LinksApi(Protocol):
    """Telegram link bookkeeping surface."""

    def record_primary_publication(
        self,
        key: str,
        episode: str,
        tier: int,
        publication: dict[str, object],
        *,
        connection: sqlite3.Connection,
    ) -> object:
        """Record one primary publication receipt inside the caller transaction."""
        ...


class DeliveryApi(Protocol):
    """Telegram delivery surface."""

    enabled: bool
    github: GitHubApi | None
    links: LinksApi

    def signal(self) -> None:
        """Wake the delivery worker."""
        ...

    def start(self) -> None:
        """Start the delivery threads."""
        ...

    def receipt(self, event: dict[str, object], receipt: dict[str, object]) -> object:
        """Record one external card receipt."""
        ...


class StorageApi(Protocol):
    """Object storage surface."""

    def ensure_object(self, key: str, exact_bytes: bytes) -> dict[str, object]:
        """Upload and verify one immutable evidence object."""
        ...


class DispatcherApi(Protocol):
    """Deferred dispatch surface."""

    enabled: bool

    def signal(self) -> None:
        """Wake the deferred dispatch loop."""
        ...

    def start(self) -> None:
        """Start the dispatcher thread."""
        ...


class QueueAdminApi(Protocol):
    """Queue administration surface."""

    def list(self, data: dict[str, object]) -> object:
        """List a bounded page of queue items."""
        ...

    def cancel(self, data: dict[str, object]) -> object:
        """Cancel one owned queue item."""
        ...


class BodyReaderApi(Protocol):
    """Structural input surface of the request-body reader."""

    headers: Message
    connection: socket
    rfile: BufferedReader


class HttpFactory(Protocol):
    """Constructor of the sealed legacy HTTP client."""

    def __call__(self) -> object:
        """Create one HTTP client."""
        ...


class GitHubFactory(Protocol):
    """Constructor of the sealed legacy GitHub adapter."""

    def __call__(self, http: object, token_file: str) -> GitHubApi:
        """Create one GitHub adapter."""
        ...


class ModelFactory(Protocol):
    """Constructor of the sealed legacy model adapter."""

    def __call__(self, http: object, key: str) -> ModelApi:
        """Create one model adapter."""
        ...


class EvidenceFactory(Protocol):
    """Constructor of the sealed legacy evidence adapter."""

    def __call__(
        self, http: object, grafana_token: str, grafana_url: str, *, github: GitHubApi
    ) -> EvidenceApi:
        """Create one evidence adapter."""
        ...


class DeliveryFactory(Protocol):
    """Constructor of the sealed legacy delivery worker."""

    def __call__(self, store: Store, token: str, *, enabled: bool) -> DeliveryApi:
        """Create one delivery worker."""
        ...


class DispatcherFactory(Protocol):
    """Constructor of the sealed legacy dispatcher worker."""

    def __call__(
        self,
        store: Store,
        token: str,
        *,
        enabled: bool,
        busy: Callable[[], bool],
    ) -> DispatcherApi:
        """Create one dispatcher worker."""
        ...


class QueueAdminFactory(Protocol):
    """Constructor of the sealed queue administration facade."""

    def __call__(self, store: Store) -> QueueAdminApi:
        """Create one queue administration facade."""
        ...


def log_event(event: str, level: str = "info", **fields: object) -> None:
    """Emit one structured operation record; never evidence or identifiers.

    Only operational counters and bounded machine codes cross this boundary:
    unknown fields are dropped and unreviewed stage or code values are redacted
    before serialization.
    """
    record: dict[str, object] = {k: v for k, v in fields.items() if k in LOG_ALLOWED_FIELDS}
    for key in ("stage", "phase", "code"):
        if key in record:
            value = record[key]
            valid = (
                (isinstance(value, str) and bool(re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", value)))
                if key == "code"
                else value in LOGGED_PHASE_NAMES
            )
            if not valid:
                record[key] = "REDACTED"
    record.update(
        ts=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        level=level,
        service="spi-triage",
        component="spi-triage",
        event=event,
        msg=event,
    )
    print(json.dumps(record, separators=(",", ":")), flush=True)


class Engine:
    """Durable stage execution engine: admission, ownership and publication."""

    def __init__(
        self,
        store: Store,
        github: GitHubApi | None = None,
        model: ModelApi | None = None,
        evidence: EvidenceApi | None = None,
        *,
        write: bool = False,
        delivery: DeliveryApi | None = None,
        storage: StorageApi | None = None,
        storage_backend: str = "legacy",
    ) -> None:
        """Bind one reviewed set of collaborators; never evidence state."""
        self.store = store
        self.github = github
        self.model = model
        self.evidence = evidence
        self.write = write
        if storage_backend not in {"legacy", "s3"}:
            msg = "Invalid storage backend"
            raise ValueError(msg)
        self.storage = storage
        self.storage_backend = storage_backend
        self.lock = threading.Lock()
        self.delivery = delivery

    def claim(self, data: dict[str, object] | None = None) -> dict[str, object]:
        """Admit a durable wait replay, or claim the next queue item."""
        if data is not None:
            return self.store.owners.claim(
                data.get("execution_id"), data.get("workflow_revision"), time.time()
            )
        # A socket call may outlive the durable lease. Never reclaim while this
        # process still owns a stage, including its final save/failure handling.
        if not self.lock.acquire(blocking=False):
            return {"job_id": ""}
        try:
            return self.store.claim()
        finally:
            self.lock.release()

    def run(self, name: str, key: str) -> dict[str, object]:
        """Run one legacy (non-durable) stage execution."""
        with self.lock:
            with self.store.db() as c:
                if c.execute(
                    "SELECT 1 FROM workflow_wait_owner WHERE job_id=? AND phase IN "
                    "('ready','waiting','running','complete')",
                    (key,),
                ).fetchone():
                    msg = "WAIT_OWNER_CONFLICT"
                    raise Failure(msg)
            REQUEST_DEADLINE.at = time.monotonic() + RUN_DEADLINE_SECONDS
            try:
                return self._run(name, key)
            except Failure as e:
                self._legacy_fail(name, key, e)
                raise
            except (
                ArithmeticError,
                AttributeError,
                IndexError,
                KeyError,
                OSError,
                TypeError,
                ValueError,
                sqlite3.Error,
            ):
                self.store.fail(key, "INTERNAL_ERROR")
                log_event("stage_failed", "error", code="INTERNAL_ERROR")
                msg = "INTERNAL_ERROR"
                raise Failure(msg) from None
            finally:
                del REQUEST_DEADLINE.at

    def _legacy_fail(self, name: str, key: str, error: Failure) -> None:
        """Apply legacy retry/failure semantics for a raised stage error."""
        current = self.store.get(key)
        if not (current["state"] == "dead" and current["error"] == "WRITE_NEEDS_REVIEW"):
            self.store.fail(
                key,
                error.code,
                retry_after=error.retry_after,
                rate_metadata=error.rate_metadata,
            )
        patient = error.code in PATIENT_TRANSIENT or (
            error.code == "OPEN_SPI_CHANGED"
            and bool(current["stage"] == 0)
            and not bool(current["intent"])
        )
        log_event(
            "stage_deferred" if patient else "stage_failed",
            "warning" if patient else "error",
            stage=name,
            code=error.code,
        )

    def run_v1(self, name: str, data: dict[str, object]) -> dict[str, object]:
        """Run one stage under the durable wait contract."""
        if not self.lock.acquire(blocking=False):
            result = cast(
                "dict[str, object]",
                self.store.owners.capacity_defer(name, data, time.time()),
            )
            if result["status"] == "deferred":
                log_event("stage_deferred", "warning", stage=name, code=result["code"])
            return result
        try:
            response, owner = self._v1_admit(name, data)
            if response is not None:
                return response
            if owner is None:
                msg = "UNSAFE_WAIT_ERROR"
                raise Failure(msg)
            return self._v1_owned(name, owner)
        finally:
            self.lock.release()

    def _v1_admit(
        self, name: str, data: dict[str, object]
    ) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        """Admit one owned v1 stage; return a replay response or a fresh owner."""
        priority = self.store.owners.capacity_defer(name, data, time.time(), priority_only=True)
        if priority is not None:
            if priority["status"] == "deferred":
                log_event("stage_deferred", "warning", stage=name, code=priority["code"])
            return priority, None
        cached, owner = self.store.owners.begin(name, data, time.time())
        if cached is not None:
            return cached, None
        return None, owner

    def _v1_owned(self, name: str, owner: dict[str, object]) -> dict[str, object]:
        """Execute one owned stage and commit its durable outcome."""
        OWNER_CONTEXT.binding = (owner["job_id"], owner["fence"])
        REQUEST_DEADLINE.at = time.monotonic() + min(
            RUN_DEADLINE_SECONDS,
            max(0.0, float(cast("float", owner["deadline"])) - time.time()),
        )
        try:
            self._run(name, str(owner["job_id"]))
        except Failure as exc:
            return self._v1_failure(name, owner, exc)
        except (
            ArithmeticError,
            AttributeError,
            IndexError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ):
            self.store.fail(
                cast("str", owner["job_id"]),
                "INTERNAL_ERROR",
                on_fail=self.store.owners.failure_callback(owner),
            )
            msg = "INTERNAL_ERROR"
            raise Failure(msg) from None
        else:
            return self.store.owners.finish(owner, deferred=False, now=time.time())
        finally:
            del REQUEST_DEADLINE.at
            del OWNER_CONTEXT.binding

    def _v1_failure(self, name: str, owner: dict[str, object], exc: Failure) -> dict[str, object]:
        """Commit the reviewed v1 outcome for one stage failure."""
        if exc.code == "OPEN_SPI_CHANGED":
            # Store reset and owner/fence/receipt changed atomically.
            # This is a normal bounded stage rewind, not a patient error
            # or a new execution/claim; real/ambiguous failures stay fatal.
            restarted = self.store.owners.snapshot_response(owner, time.time())
            if restarted is not None:
                log_event("snapshot_revalidated", stage="match", code=exc.code)
                return restarted
        if exc.code in {"LLM_ADMISSION_DEFERRED", "GITHUB_READ_TIMEOUT"}:
            try:
                deferred = self.store.owners.finish(
                    owner,
                    deferred=True,
                    now=time.time(),
                    retry_after=exc.retry_after,
                    code=exc.code,
                )
            except Failure as terminal:
                exc = terminal
            else:
                log_event("stage_deferred", "warning", stage=name, code=exc.code)
                return deferred
        self.store.fail(
            cast("str", owner["job_id"]),
            exc.code,
            retry_after=exc.retry_after,
            rate_metadata=exc.rate_metadata,
            on_fail=self.store.owners.failure_callback(owner),
        )
        log_event("stage_failed", "error", stage=name, code=exc.code)
        raise exc

    def _run(self, name: str, key: str) -> dict[str, object]:
        """Validate stage order and dispatch to one stage implementation."""
        stages = {"match": 1, "collect": 2, "analyze": 3, "publish": 4}
        if name not in stages:
            msg = "INVALID_STAGE"
            raise Failure(msg)
        job = self.store.get(key)
        wanted = stages[name]
        if job["state"] == "dead" and job["error"] == "WRITE_NEEDS_REVIEW":
            msg = "WRITE_NEEDS_REVIEW"
            raise Failure(msg)
        stage = cast("int", job["stage"])
        if stage >= wanted:
            return {"job_id": key, "status": job["state"], "stage": stage}
        if stage != wanted - 1 or job["state"] != "processing":
            msg = "INVALID_STAGE_ORDER"
            raise Failure(msg)
        record = cast("dict[str, object]", job["result"])
        event = cast("dict[str, object]", job["event"])
        resolved = event["status"] == "resolved"
        intent = bool(job["intent"])
        if not intent:
            self.store.snapshot_guard(key)
        if name == "match":
            self._run_match(key, record, event, resolved=resolved)
        elif name == "collect":
            self._run_collect(record, event, resolved=resolved)
        elif name == "analyze":
            self._run_analyze(key, record, event, resolved=resolved, intent=intent)
        else:
            return self._run_publish(key, record, event, resolved=resolved, intent=intent)
        self.store.save(key, wanted, record)
        return {"job_id": key, "status": "processing", "stage": wanted}

    def _run_match(
        self,
        key: str,
        record: dict[str, object],
        event: dict[str, object],
        *,
        resolved: bool,
    ) -> None:
        """Run the match stage retry-safely across worker restarts."""
        if resolved:
            record["resolved_issue"] = self.store.episode_issue(str(event["episode"]))
            if self.delivery is not None and not bool(record["resolved_issue"]):
                record["analyze_recovery"] = True
        if not resolved or bool(record.get("analyze_recovery")):
            issues = cast("GitHubApi", self.github).snapshot()
            record["open_signature"] = digest([(x["number"], x["updated_at"]) for x in issues])

            def checkpoint(progress: object) -> None:
                """Persist one reviewed match progress checkpoint."""

                def retain(c: sqlite3.Connection) -> None:
                    """Store the checkpoint atomically with the stage save."""
                    c.execute(
                        "INSERT OR REPLACE INTO match_review_v3 VALUES(?,?)",
                        (key, json.dumps(progress)),
                    )

                record["match_progress_v3"] = progress
                self.store.save(key, 0, record, on_save=retain)

            record["match"] = cast("ModelApi", self.model).match(
                event,
                issues,
                progress=self.store.match_checkpoint(key) or record.get("match_progress_v3"),
                on_progress=checkpoint,
            )

    def _run_collect(
        self, record: dict[str, object], event: dict[str, object], *, resolved: bool
    ) -> None:
        """Run the collect stage for unresolved episodes."""
        if (
            not resolved
            or bool(record.get("resolved_issue"))
            or bool(record.get("analyze_recovery"))
        ):
            record["evidence"] = cast("EvidenceApi", self.evidence).collect(event)

    def _run_analyze(
        self,
        key: str,
        record: dict[str, object],
        event: dict[str, object],
        *,
        resolved: bool,
        intent: bool,
    ) -> None:
        """Run the analyze stage with the reviewed snapshot guard."""
        github = cast("GitHubApi", self.github)
        if not resolved or bool(record.get("analyze_recovery")):
            if not intent and github.open_signature() != record["open_signature"]:
                self.invalidate_snapshot(key, record, self.store.get(key))
            record["report"] = cast("ModelApi", self.model).analyze(
                event, record["match"], record["evidence"]
            )
            render(cast("dict[str, object]", record["report"]), event)

    def _publish_targets(
        self,
        key: str,
        record: dict[str, object],
        event: dict[str, object],
        marker: str,
        *,
        resolved: bool,
    ) -> tuple[str, str, object] | dict[str, object]:
        """Resolve the publication target, title and body."""
        if resolved and not bool(record.get("analyze_recovery")):
            number = record["resolved_issue"]
            github = cast("GitHubApi", self.github)
            if not bool(number):
                self.store.save(key, 4, record, state="complete", issue=0)
                return {"job_id": key, "status": "resolved_without_open_spi"}
            existing = github.request("GET", "/issues/" + str(number))
            if existing.get("state") != "open":
                self.store.save(key, 4, record, state="complete", issue=number or 0)
                return {"job_id": key, "status": "resolved_without_open_spi"}
            ends = event["endsAt"]
            resolution = str(ends) if bool(ends) else "an unspecified time"
            title = ""
            body = (
                "## Incident resolved\n\nObserved recovery at "
                + resolution
                + ".\n\nResolution does not establish root-cause remediation; this issue"
                " remains open.\n\n" + marker
            )
            return title, body, number
        github = cast("GitHubApi", self.github)
        issues = github.snapshot()
        if digest([(x["number"], x["updated_at"]) for x in issues]) != record["open_signature"]:
            self.invalidate_snapshot(key, record, self.store.get(key))
        title, body = render(cast("dict[str, object]", record["report"]), event)
        report = cast("dict[str, object]", record["report"])
        report_number = report["issue_number"]
        candidates = cast(
            "list[dict[str, object]]",
            cast("dict[str, object]", record["match"])["candidates"],
        )
        if report_number not in {0, *[x["number"] for x in candidates]}:
            msg = "INVALID_MATCH_TARGET"
            raise Failure(msg)
        return title, body, report_number

    def _publish_intent(
        self,
        key: str,
        record: dict[str, object],
        event: dict[str, object],
        job: dict[str, object],
    ) -> dict[str, object]:
        """Complete one already-published primary intent."""
        if record["publication_backend"] == "s3":
            self.upload_evidence(key, record, intent=job["intent"])
        intent = json.loads(str(job["intent"]))
        number: object = (
            intent["number"]
            if intent.get("primary_done")
            else cast("GitHubApi", self.github).reconcile(marker(key), intent["number"])
        )
        if not bool(number):
            msg = "WRITE_NEEDS_REVIEW"
            raise Failure(msg)
        if self.delivery is not None and not bool(record.get("primary_publication")):
            publication = cast("GitHubApi", self.github).primary_reference(
                marker(key), int(cast("int", number))
            )
            self.save_primary(key, record, event, publication)
        self.finish_evidence(key, record, number)
        return {"job_id": key, "status": "reconciled", "issue_number": number}

    def _run_publish(
        self,
        key: str,
        record: dict[str, object],
        event: dict[str, object],
        *,
        resolved: bool,
        intent: bool,
    ) -> dict[str, object]:
        """Run the publish stage under the reviewed write contract."""
        job = self.store.get(key)
        if not self.write:
            self.store.save(key, 4, record, state="dry_run")
            return {"job_id": key, "status": "dry_run", "issue_number": 0}
        if "publication_backend" not in record:
            record["publication_backend"] = (
                "legacy" if intent or "artifact_publication" in record else self.storage_backend
            )
            self.store.save(key, 3, record, intent=job["intent"])
        if record["publication_backend"] not in {"legacy", "s3"}:
            msg = "STORAGE_INTEGRITY"
            raise Failure(msg)
        # Reconcile BEFORE checking open candidates: the previous write may itself
        # have changed that snapshot, or a human may have closed the created issue.
        if intent:
            return self._publish_intent(key, record, event, job)
        # Without a trusted primary intent the artifact target cannot be
        # inferred from a fresh match. Retain all legacy receipts for review.
        if "artifact_publication" in record:
            msg = "WRITE_NEEDS_REVIEW"
            raise Failure(msg)
        targets = self._publish_targets(key, record, event, marker(key), resolved=resolved)
        if isinstance(targets, dict):
            return targets
        rendered = self._render_publication(key, record, job, targets, resolved=resolved)
        if isinstance(rendered, dict):
            return rendered
        self.store.save(key, 3, record, intent=json.dumps({"number": targets[2]}))
        self._publish_post(key, record, event, (targets[0], rendered, targets[2]))
        log_event("publication_ok")
        return {"job_id": key, "status": "published", "issue_number": targets[2]}

    def _render_publication(
        self,
        key: str,
        record: dict[str, object],
        job: dict[str, object],
        targets: tuple[str, str, object],
        *,
        resolved: bool,
    ) -> str | dict[str, object]:
        """Render the reviewed publication body for the resolved backend."""
        body = targets[1]
        number = targets[2]
        if record["publication_backend"] == "s3":
            objects = self.upload_evidence(key, record)
            if not resolved or bool(record.get("analyze_recovery")):
                github = cast("GitHubApi", self.github)
                issues = github.snapshot()
                digest_fresh = digest([(item["number"], item["updated_at"]) for item in issues])
                if digest_fresh != record["open_signature"]:
                    self.invalidate_snapshot(key, record, job)
            elif not self._issue_open(number):
                self.store.save(key, 4, record, state="complete", issue=number)
                return {"job_id": key, "status": "resolved_without_open_spi"}
            return repair_markdown_links(body + storage_markdown(objects))
        bundle = cast("dict[str, object]", record.get("evidence", {})).get("bundle")
        return repair_markdown_links(body + index_markdown(bundle))

    def _issue_open(self, number: object) -> bool:
        """Verify the resolved episode still has its open issue."""
        existing = cast("GitHubApi", self.github).request("GET", "/issues/" + str(number))
        return bool(existing.get("state") == "open")

    def _publish_post(
        self,
        key: str,
        record: dict[str, object],
        event: dict[str, object],
        targets: tuple[str, str, object],
    ) -> None:
        """Post the review comment or issue, never retrying ambiguous writes."""
        title, body, number = targets
        github = cast("GitHubApi", self.github)
        posted: dict[str, object]
        kind: str
        try:
            if bool(number):
                posted = github.request(
                    "POST", "/issues/" + str(number) + "/comments", {"body": body}
                )
                kind = "comment"
            else:
                posted = github.request("POST", "/issues", {"title": title, "body": body})
                number = posted["number"]
                kind = "issue"
        except Failure as e:
            # 4xx are definitive rejections. Network errors/5xx can hide a
            # successful write: keep intent and never blindly repeat the POST.
            if e.code.startswith("HTTP_4") and e.code != "HTTP_408":
                self.store.save(key, 3, record, intent=None)
            raise
        if self.delivery is not None:
            publication = {
                "kind": kind,
                "issue_number": number,
                "id": posted.get("id"),
                "html_url": posted.get("html_url"),
                "role": "primary",
            }
            self.save_primary(key, record, event, publication)
        self.finish_evidence(key, record, number)

    def invalidate_snapshot(
        self, key: str, result: dict[str, object], job: dict[str, object]
    ) -> None:
        """Revoke a stale snapshot and rewind to the reviewed re-match."""
        if bool(job["intent"]) or "artifact_publication" in result:
            msg = "WRITE_NEEDS_REVIEW"
            raise Failure(msg)
        retained = dict(result)
        # Uploaded immutable objects keep their original evidence binding forever.
        if "storage_publication" in retained:
            audit = list(cast("list[object]", retained.get("snapshot_audit", [])))
            audit.append(
                {k: retained.get(k) for k in ("evidence", "storage_publication", "open_signature")}
            )
            retained["snapshot_audit"] = audit
            del retained["storage_publication"]
        for field in ("match", "report", "evidence", "open_signature"):
            retained.pop(field, None)
        self.store.replace_snapshot(
            key,
            self.store.get(key),
            retained,
            expensive="report" in result or "storage_publication" in result,
        )
        msg = "OPEN_SPI_CHANGED"
        raise Failure(msg, retry_after=SNAPSHOT_RECHECK_SECONDS)

    def upload_evidence(
        self, key: str, result: dict[str, object], intent: object = None
    ) -> list[tuple[str, bytes]]:
        """Upload the immutable evidence bundle under verified bindings."""
        objects = storage_objects(
            cast("dict[str, object]", result.get("evidence", {})).get("bundle")
        )
        binding = [
            {
                "bucket": "spi-evidence",
                "key": object_key,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
                "verified": True,
            }
            for object_key, raw in objects
        ]
        progress = cast(
            "dict[str, object]",
            result.setdefault("storage_publication", {"binding": binding, "verified": []}),
        )
        verified = cast("list[object]", progress.get("verified", []))
        if (
            progress.get("binding") != binding
            or progress.get("verified") != binding[: len(verified)]
        ):
            msg = "STORAGE_INTEGRITY"
            raise Failure(msg)

        def save() -> None:
            """Persist the continuing upload progress intent-compatibly."""
            if intent is None:
                self.store.save(key, 3, result)
            else:
                self.store.save(key, 3, result, intent=intent)

        save()
        for i, (object_key, raw) in enumerate(objects):
            if i < len(cast("list[object]", progress["verified"])):
                continue
            verified_one = self._ensure_object(object_key, raw)
            if verified_one != binding[i]:
                msg = "STORAGE_INTEGRITY"
                raise Failure(msg)
            cast("list[object]", progress["verified"]).append(verified_one)
            save()
        return objects

    def _ensure_object(self, object_key: str, raw: bytes) -> dict[str, object]:
        """Upload one immutable object or translate reviewed storage errors."""
        if self.storage is None:
            msg = "STORAGE_CONFIG"
            raise Failure(msg)
        try:
            return self.storage.ensure_object(object_key, raw)
        except StorageTransient as exc:
            msg = "STORAGE_TRANSIENT"
            raise Failure(msg, exc.retry_after) from None
        except StorageConflict:
            msg = "STORAGE_CONFLICT"
            raise Failure(msg) from None
        except StoragePermanent:
            msg = "STORAGE_PERMANENT"
            raise Failure(msg) from None

    def save_primary(
        self,
        key: str,
        result: dict[str, object],
        event: dict[str, object],
        publication: dict[str, object],
    ) -> None:
        """Persist one trusted primary publication receipt."""
        try:
            primary_url(publication)
        except ValueError:
            msg = "INVALID_PRIMARY_REFERENCE"
            raise Failure(msg) from None
        result["primary_publication"] = publication
        delivery = cast("DeliveryApi", self.delivery)

        def queue(c: sqlite3.Connection) -> None:
            """Record the primary receipt inside the save transaction."""
            delivery.links.record_primary_publication(
                key,
                str(event["episode"]),
                2 if event["status"] == "resolved" else 1,
                publication,
                connection=c,
            )

        self.store.save(
            key,
            3,
            result,
            intent=json.dumps({"number": publication["issue_number"], "primary_done": True}),
            on_save=queue,
        )
        delivery.signal()

    def finish_evidence(self, key: str, result: dict[str, object], number: object) -> None:
        """Publish artifacts and mark the job complete."""
        intent = json.dumps({"number": number, "primary_done": True})
        progress = cast("dict[str, object]", result.setdefault("artifact_publication", {}))

        def save() -> None:
            """Persist the continuing artifact publication progress."""
            self.store.save(key, 3, result, intent=intent)

        save()
        if result.get("publication_backend", "legacy") == "legacy":
            bundle = cast("dict[str, object]", result.get("evidence", {})).get("bundle")
            publish_parts(
                cast("GitHubApi", self.github),
                int(cast("int", number)),
                bundle,
                progress,
                save,
            )
        else:
            self.upload_evidence(key, result, intent=intent)
        self.store.save(key, 4, result, state="complete", issue=number, intent=None)


def read_request_body(
    handler: BodyReaderApi, timeout: float = READ_BODY_TIMEOUT_SECONDS
) -> dict[str, object]:
    """Bound partial or trickling request bodies by a total elapsed deadline."""
    try:
        length = int(str(handler.headers.get("Content-Length", "0")))
    except (TypeError, ValueError):
        msg = "INVALID_BODY_SIZE"
        raise Failure(msg) from None
    if not 0 < length <= MAX_BODY_BYTES:
        msg = "INVALID_BODY_SIZE"
        raise Failure(msg)
    deadline = time.monotonic() + timeout
    previous = handler.connection.gettimeout()
    try:
        chunks = _read_chunks(handler, length, deadline)
        payload = json.loads(b"".join(chunks))
    except TimeoutError:
        msg = "REQUEST_BODY_TIMEOUT"
        raise Failure(msg) from None
    finally:
        handler.connection.settimeout(previous)
    if not isinstance(payload, dict):
        msg = "INVALID_REQUEST"
        raise Failure(msg)
    return cast("dict[str, object]", payload)


def _read_chunks(handler: BodyReaderApi, length: int, deadline: float) -> list[bytes]:
    """Read one bounded request body chunk-wise honoring the total deadline."""
    chunks: list[bytes] = []
    while length:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        handler.connection.settimeout(remaining)
        chunk = handler.rfile.read1(length)
        if not chunk:
            msg = "INCOMPLETE_BODY"
            raise Failure(msg)
        chunks.append(chunk)
        length -= len(chunk)
    return chunks


def marker(key: str) -> str:
    """Return the immutable issue marker containing the reviewed key."""
    return "<!-- socrat-spi:" + key + " -->"


@dataclass(frozen=True)
class WorkerContext:
    """Reviewed connection state shared by one worker process."""

    store: Store
    engine: Engine
    delivery: DeliveryApi
    dispatcher: DispatcherApi
    admin: QueueAdminApi | None
    queue_token: str
    authorized_call: Callable[[Message, str], bool] | None


class Worker(ThreadingHTTPServer):
    """Worker HTTP server carrying the reviewed context."""

    context: WorkerContext

    def __init__(self, context: WorkerContext) -> None:
        """Bind to the container-side address scoped by network policy."""
        self.context = context
        super().__init__(("", WORKER_PORT), Handler)


class Handler(BaseHTTPRequestHandler):
    """Authenticated worker request handler."""

    server: Worker

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Silence the default per-request noise log."""

    def send(self, status: int, body: object, content_type: str = "application/json") -> None:
        """Send one bounded response body."""
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(raw)

    def do_GET(self) -> None:
        """Serve the health and metrics surfaces."""
        if self.path == "/healthz":
            self.send(HTTP_OK, {"status": "ok"})
            return
        if self.path == "/metrics":
            self.send_metrics()
            return
        self.send(404, {"code": "NOT_FOUND"})

    def send_metrics(self) -> None:
        """Render the reviewed queue and dispatch gauges."""
        context = self.server.context
        healthy = context.store.health()
        lines = ["# TYPE socrat_spi_jobs gauge"]
        lines.extend(
            'socrat_spi_jobs{state="'
            + state
            + '"} '
            + str(cast("dict[str, object]", healthy["counts"]).get(state, 0))
            for state in JOB_METRIC_STATES
        )
        lines += [
            "# TYPE socrat_spi_oldest_pending_seconds gauge",
            "socrat_spi_oldest_pending_seconds " + str(healthy["oldest_pending_seconds"]),
        ]
        with context.store.db() as c:
            pending = c.execute("SELECT count(*)FROM spi_links WHERE state!='applied'").fetchone()[
                0
            ]
        lines += [
            "socrat_spi_telegram_links_pending " + str(pending),
            "socrat_spi_telegram_links_enabled " + str(int(context.delivery.enabled)),
        ]
        dispatched = context.store.dispatch_status()
        lines += [
            "socrat_spi_dispatch_enabled " + str(int(context.dispatcher.enabled)),
            "socrat_spi_dispatch_attempts " + str(dispatched["attempts"]),
        ]
        self.send(HTTP_OK, "\n".join(lines) + "\n", "text/plain; version=0.0.4")

    def do_POST(self) -> None:
        """Serve the authenticated queue and workflow surfaces."""
        if self.path in ("/operator/queue/list", "/operator/queue/cancel"):
            self.post_queue_admin()
            return
        headers = cast("Message", self.headers)
        if not hmac.compare_digest(headers.get("X-Worker-Token", ""), os.environ["WORKER_TOKEN"]):
            self.send(403, {"code": "FORBIDDEN"})
            return
        try:
            data = read_request_body(cast("BodyReaderApi", self))
            opted = self.workflow_opted(headers)
            result = self.post_route(data, opted=opted)
        except Failure as e:
            self.close_connection = True
            self.send(422, {"code": e.code})
            return
        except (ValueError, TypeError, AttributeError):
            self.send(400, {"code": "INVALID_REQUEST"})
            return
        except (
            ArithmeticError,
            IndexError,
            KeyError,
            OSError,
            sqlite3.Error,
        ):
            self.send(500, {"code": "INTERNAL_ERROR"})
            return
        finally:
            self.server.context.dispatcher.signal()
        if result is None:
            self.send(404, {"code": "NOT_FOUND"})
            return
        self.send(202 if opted and result.get("status") == "deferred" else HTTP_OK, result)

    @staticmethod
    def workflow_opted(headers: Message) -> bool:
        """Validate the reviewed workflow contract header selections."""
        contract = headers.get("X-SPI-Workflow-Contract")
        if contract not in (None, "1"):
            msg = "INVALID_WORKFLOW_CONTRACT"
            raise Failure(msg)
        opted = contract == "1"
        if opted and os.environ.get("SPI_DURABLE_WAIT_ENABLED", "false") != "true":
            msg = "WORKFLOW_CONTRACT_DISABLED"
            raise Failure(msg)
        return opted

    def post_queue_admin(self) -> None:
        """Serve the token-gated queue administration endpoints."""
        context = self.server.context
        authorized_call = context.authorized_call
        panel = context.admin
        if (
            panel is None
            or authorized_call is None
            or not authorized_call(cast("Message", self.headers), context.queue_token)
        ):
            self.send(403, {"code": "FORBIDDEN"})
            return
        try:
            data = read_request_body(cast("BodyReaderApi", self))
            if self.path.endswith("/list"):
                self.send(HTTP_OK, panel.list(data))
                return
            result = panel.cancel(data)
            context.dispatcher.signal()
            self.send(HTTP_OK, result)
        except Failure as e:
            self.send(
                409 if e.code in {"QUEUE_ITEM_CHANGED", "QUEUE_ITEM_NOT_CANCELLABLE"} else 400,
                {"code": e.code},
            )
        except (ValueError, TypeError, AttributeError):
            self.send(400, {"code": "INVALID_REQUEST"})
        except (ArithmeticError, IndexError, KeyError, OSError, sqlite3.Error):
            self.send(500, {"code": "INTERNAL_ERROR"})

    def post_route(self, data: dict[str, object], *, opted: bool) -> dict[str, object] | None:
        """Route one authenticated stage request; None selects the 404."""
        context = self.server.context
        if self.path == "/enqueue":
            return context.store.enqueue(normalize(data))
        if self.path == "/enqueue-group":
            return self.post_enqueue_group(data)
        if self.path == "/telegram-receipt":
            return self.post_telegram_receipt(data)
        if self.path == "/claim":
            return self.post_claim(data, opted=opted)
        if self.path in ("/match", "/collect", "/analyze", "/publish"):
            return self.post_stage(data, opted=opted)
        return None

    def post_enqueue_group(self, data: dict[str, object]) -> dict[str, object]:
        """Enqueue one bounded alert group as separate events."""
        context = self.server.context
        alerts = data.get("alerts")
        if not isinstance(alerts, list) or not 0 < len(alerts) <= MAX_ALERT_GROUP:
            msg = "INVALID_ALERT_GROUP"
            raise Failure(msg)
        events = [
            normalize({"source": data.get("externalURL", "socrat-alerts"), "alert": a})
            for a in alerts
        ]
        accepted = context.store.enqueue_many(events)
        return {
            "accepted": len(accepted),
            "events": [{"event_key": e["event_key"], "episode": e["episode"]} for e in events],
        }

    def post_telegram_receipt(self, data: dict[str, object]) -> dict[str, object]:
        """Record one reviewed external card receipt."""
        context = self.server.context
        result = record_receipt(context.store, data)
        receipt = data.get("receipt")
        if isinstance(receipt, dict) and not bool(receipt.get("error")):
            context.delivery.receipt({"episode": result["episode"]}, receipt)
        return result

    def post_claim(self, data: dict[str, object], *, opted: bool) -> dict[str, object]:
        """Claim one durable wait replay or the next queue item."""
        context = self.server.context
        claimed = context.engine.claim(data if opted else None)
        healthy = context.store.health()
        log_event(
            "queue_health",
            oldest_pending_seconds=healthy["oldest_pending_seconds"],
            dead_jobs=cast("dict[str, object]", healthy["counts"]).get("dead", 0),
        )
        return claimed

    def post_stage(self, data: dict[str, object], *, opted: bool) -> dict[str, object]:
        """Run one reviewed stage request."""
        key = data.get("job_id", "")
        if (
            not isinstance(key, str)
            or len(key) != JOB_ID_HEX_LENGTH
            or any(char not in "0123456789abcdef" for char in key)
        ):
            msg = "INVALID_JOB_ID"
            raise Failure(msg)
        engine = self.server.context.engine
        if opted:
            return engine.run_v1(self.path[1:], data)
        return engine.run(self.path[1:], key)


def _heartbeat(store: Store) -> None:
    """Loop the bounded queue health record."""
    while True:
        try:
            healthy = store.health()
            with store.db() as c:
                pending = c.execute(
                    "SELECT count(*)FROM spi_links WHERE state!='applied'"
                ).fetchone()[0]
            log_event(
                "queue_health",
                oldest_pending_seconds=healthy["oldest_pending_seconds"],
                dead_jobs=cast("dict[str, object]", healthy["counts"]).get("dead", 0),
                telegram_links_pending=pending,
            )
        except (KeyError, OSError, TypeError, ValueError, sqlite3.Error):
            log_event("health_read_failed", "error")
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)


def serve() -> None:
    """Run the single worker HTTP surface."""
    os.umask(0o077)
    # Fail closed before store recovery, claims or dispatch.
    storage, storage_backend = load_storage()
    model = Model(HTTP(), os.environ["LITELLM_KEY"])
    http = HTTP()
    store = Store(
        os.environ.get("SPI_DATABASE", "/data/spi.sqlite"),
        minute_token_limit=int(os.environ.get("SPI_LLM_MINUTE_TOKENS", "30000")),
    )
    model.store = store
    admin: QueueAdminApi | None = None
    queue_token = ""
    authorized_call: Callable[[Message, str], bool] | None = None
    if os.environ.get("SPI_QUEUE_UI_ENABLED") == "true":
        from pathlib import Path

        from queue_admin import QueueAdmin
        from queue_admin import authorized as queue_authorized

        queue_token = Path("/queue-control/token").read_text().strip()
        if len(queue_token) < MIN_QUEUE_TOKEN_CHARS:
            msg = "QUEUE_ADMIN_TOKEN_REQUIRED"
            raise RuntimeError(msg)
        admin_factory: QueueAdminFactory = QueueAdmin
        admin = admin_factory(store)
        authorized_call = queue_authorized
    recovered = store.recover_on_start()
    log_event("worker_started", recovered_jobs=recovered)
    delivery = Delivery(
        store,
        os.environ.get("BOT_INTERNAL_TOKEN", ""),
        enabled=os.environ.get("SPI_TELEGRAM_LINKS_ENABLED", "false") == "true",
    )
    delivery_factory = cast("DeliveryApi", delivery)
    token_file = os.environ.get("GITHUB_TOKEN_FILE", "/github/token")
    engine = Engine(
        store,
        cast("GitHubApi", GitHub(http, token_file)),
        cast("ModelApi", model),
        Evidence(
            http,
            os.environ["GRAFANA_TOKEN"],
            os.environ["GRAFANA_URL"],
            github=GitHub(http, token_file),
        ),
        write=os.environ.get("WRITE_ENABLED") == "true",
        delivery=delivery_factory,
        storage=cast("StorageApi | None", storage),
        storage_backend=storage_backend,
    )
    delivery.github = engine.github
    dispatcher = Dispatcher(
        store,
        os.environ["WORKER_TOKEN"],
        enabled=os.environ.get("SPI_DISPATCH_ENABLED", "false") == "true",
        busy=engine.lock.locked,
    )
    dispatcher.start()
    delivery.start()
    threading.Thread(target=_heartbeat, args=(store,), name="spi-health", daemon=True).start()
    Worker(
        WorkerContext(
            store,
            engine,
            delivery_factory,
            cast("DispatcherApi", dispatcher),
            admin,
            queue_token,
            authorized_call,
        )
    ).serve_forever()


if __name__ == "__main__":
    serve()
