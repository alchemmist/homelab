"""Durable original-card decoration outbox; no GitHub/model dependencies.

Transport: request(method, path, json=None) -> (HTTP status, decoded dict).
It owns credentials/timeouts and MUST NOT log headers or response bodies.
The current legacy bot cannot safely deliver: guarded_protocol defaults False.
Enable only against reviewed immutable episode-key + per-copy acknowledgement API.
"""

import json
import re
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol, cast

LINK_LEASE_SECONDS = 120
# Reviewed GitHub permalink surface; nothing else is accepted as primary.
_URL = re.compile(
    r"https://github\.com/alchemmist/homelab/issues/([1-9][0-9]*)(?:#issuecomment-([1-9][0-9]*))?\Z"
)
# Outbox state, error codes and budget bounds pinned by the spi_triage suite.
CARD_RECEIPT_FIELDS = ("key", "episode", "immutable_key", "copies")
COPY_FIELDS = ("chat_id", "message_id")
LABEL = "SPI"
HTTP_OK = 200
CARD_NOT_READY_STATUSES = (404, 409)
MIN_REVISION = 1
RETRY_DELAY_CAP = 3600
RETRY_ATTEMPT_CAP = 11
RETRY_CLOCK_MIN = 0.75
RETRY_CLOCK_SPREAD = 0.5
APPLIED_RESCHEDULE = 21600
EPISODE_MISMATCH = "EPISODE_MISMATCH"
RECEIPT_CONFLICT = "RECEIPT_CONFLICT"
REVISION_CONFLICT = "REVISION_CONFLICT"
INVALID_REVISION = "INVALID_REVISION"
INVALID_PRIMARY_URL = "INVALID_PRIMARY_URL"
INVALID_PRIMARY_RECEIPT = "INVALID_PRIMARY_RECEIPT"
WAIT_RECEIPT = "WAIT_RECEIPT"
BOT_GUARD_REQUIRED = "BOT_GUARD_REQUIRED"
WAIT_IMMUTABLE_RECEIPT = "WAIT_IMMUTABLE_RECEIPT"
CARD_NOT_READY = "CARD_NOT_READY"
BOT_HTTP_ERROR = "BOT_HTTP_ERROR"
COPIES_PENDING = "COPIES_PENDING"
DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"


class _StoreHost(Protocol):
    """Durable-link table owner: one immediate transaction at a time."""

    def db(self) -> AbstractContextManager[sqlite3.Connection]:
        """Yield the single-writer connection context."""
        ...


class _Transport(Protocol):
    """Bot API transport callback owning credentials and timeouts."""

    def __call__(self, method: str, path: str, json: object = None) -> tuple[int, object]:
        """Perform one bot call returning (HTTP status, decoded body)."""
        ...


def primary_url(publication: dict[str, object]) -> str:
    """Return the only trusted primary permalink for the reviewed repository."""
    url = publication.get("html_url", "")
    match = _URL.fullmatch(url) if isinstance(url, str) else None
    if not match or int(match[1]) != publication.get("issue_number"):
        msg = INVALID_PRIMARY_URL
        raise ValueError(msg)
    if publication.get("kind") == "issue":
        valid = match[2] is None
    else:
        valid = (
            publication.get("kind") == "comment"
            and match[2] is not None
            and int(match[2]) == publication.get("id")
        )
    if not valid or publication.get("role") != "primary":
        msg = INVALID_PRIMARY_RECEIPT
        raise ValueError(msg)
    return cast("str", url)


class Links:
    """Durable original-card link outbox with per-episode revision state."""

    def __init__(
        self,
        store: _StoreHost,
        request: _Transport,
        clock: Callable[[], float] = time.time,
        jitter: Callable[[], float] = lambda: 0.5,
        *,
        guarded_protocol: bool = False,
    ) -> None:
        """Bind the store, transport and clocks, and ensure the outbox tables."""
        self.store, self.request, self.clock = store, request, clock
        self.jitter, self.guarded = jitter, guarded_protocol
        with store.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS spi_card_receipts (
              episode TEXT PRIMARY KEY, receipt TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS spi_links (
              episode TEXT PRIMARY KEY, event_key TEXT NOT NULL, revision INTEGER NOT NULL,
              url TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
              available REAL NOT NULL DEFAULT 0, lease REAL NOT NULL DEFAULT 0,
              owner TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
              acknowledgement TEXT NOT NULL DEFAULT '{}');
            """)

    def record_card_receipt(
        self, episode: str, receipt: dict[str, object], connection: object = None
    ) -> None:
        """Store only card identity, never original alert text/credentials."""
        safe = {k: receipt[k] for k in CARD_RECEIPT_FIELDS if k in receipt}
        safe["copies"] = [
            {k: x[k] for k in COPY_FIELDS if k in x}
            for x in cast("list[dict[str, object]]", safe.get("copies", []))
        ]
        if safe.get("episode", episode) != episode:
            msg = EPISODE_MISMATCH
            raise ValueError(msg)

        def save(c: sqlite3.Connection) -> None:
            """Merge the copy acknowledgement set inside one transaction."""
            previous = c.execute(
                "SELECT receipt FROM spi_card_receipts WHERE episode=?", (episode,)
            ).fetchone()
            encoded = json.dumps(safe, sort_keys=True)
            if previous:
                old = json.loads(previous[0])
                if old.get("key") != safe.get("key") or old.get("episode") != safe.get("episode"):
                    msg = RECEIPT_CONFLICT
                    raise ValueError(msg)
                merged = {
                    (x["chat_id"], x["message_id"])
                    for x in cast("list[dict[str, object]]", old.get("copies", []))
                }
                merged.update(
                    (x["chat_id"], x["message_id"])
                    for x in cast("list[dict[str, object]]", safe.get("copies", []))
                )
                safe["copies"] = [
                    {"chat_id": chat, "message_id": message} for chat, message in sorted(merged)
                ]
                safe["immutable_key"] = (
                    old.get("immutable_key") is True or safe.get("immutable_key") is True
                )
            encoded = json.dumps(safe, sort_keys=True)
            c.execute(
                "INSERT INTO spi_card_receipts VALUES (?,?) ON CONFLICT(episode) "
                "DO UPDATE SET receipt=excluded.receipt",
                (episode, encoded),
            )
            if not previous or previous[0] != encoded:
                c.execute(
                    "UPDATE spi_links SET state='pending',available=0 WHERE episode=?", (episode,)
                )

        if connection is not None:
            save(cast("sqlite3.Connection", connection))
        else:
            with self.store.db() as c:
                save(c)

    def record_primary_publication(
        self,
        key: str,
        episode: str,
        tier: object,
        publication: dict[str, object],
        connection: object = None,
    ) -> None:
        """Record the trusted primary permalink, rejecting stale revisions."""
        url = primary_url(publication)
        if not isinstance(tier, int) or isinstance(tier, bool) or tier < MIN_REVISION:
            msg = INVALID_REVISION
            raise ValueError(msg)

        def save(c: sqlite3.Connection) -> None:
            """Apply one primary revision under first-writer CAS semantics."""
            row = c.execute("SELECT * FROM spi_links WHERE episode=?", (episode,)).fetchone()
            if row and tier <= row["revision"]:
                if tier == row["revision"] and (url != row["url"] or key != row["event_key"]):
                    msg = REVISION_CONFLICT
                    raise ValueError(msg)
                return
            c.execute(
                """INSERT INTO spi_links(episode,event_key,revision,url) VALUES(?,?,?,?)
              ON CONFLICT(episode) DO UPDATE SET event_key=excluded.event_key,
              revision=excluded.revision,url=excluded.url,state='pending',available=0,
              attempts=0,error=NULL,acknowledgement='{}' """,
                (episode, key, tier, url),
            )

        if connection is not None:
            save(cast("sqlite3.Connection", connection))
        else:
            with self.store.db() as c:
                save(c)

    def snapshot(self, episode: str) -> dict[str, object] | None:
        """Return one outbox row as a plain dict for callers and tests."""
        with self.store.db() as c:
            row = c.execute("SELECT * FROM spi_links WHERE episode=?", (episode,)).fetchone()
            return dict(row) if row else None

    def once(self) -> bool:
        """One bounded attempt. Run on a dedicated thread, never the dispatch loop.

        Reviewed bot contract: immutable timestamp-derived episode keys,
        expected_copies atomic guard, retryable failed edits and explicit updated/
        pending copy sets. Desired-state GET readback is never delivery evidence.
        Serialize newer episode revisions in the caller; local CAS protects state
        but cannot cancel an older in-flight remote edit.
        """
        now, owner = self.clock(), uuid.uuid4().hex
        with self.store.db() as c:
            row = c.execute(
                "SELECT * FROM spi_links WHERE state!='applied' AND available<=? "
                "AND lease<=? ORDER BY available,episode LIMIT 1",
                (now, now),
            ).fetchone()
            if row is None:
                return False
            row = dict(row)
            c.execute(
                "UPDATE spi_links SET lease=?,owner=?,attempts=attempts+1 WHERE episode=?",
                (now + LINK_LEASE_SECONDS, owner, row["episode"]),
            )
            receipt = c.execute(
                "SELECT receipt FROM spi_card_receipts WHERE episode=?", (row["episode"],)
            ).fetchone()
        error: str | None = WAIT_RECEIPT
        ack: dict[str, object] = {}
        applied = False
        try:
            receipt_map = json.loads(receipt[0]) if receipt else {}
            if receipt_map.get("key"):
                if not self.guarded:
                    error = BOT_GUARD_REQUIRED
                elif (
                    receipt_map.get("episode") != row["episode"]
                    or receipt_map.get("immutable_key") is not True
                    or not receipt_map.get("copies")
                ):
                    error = WAIT_IMMUTABLE_RECEIPT
                else:
                    # immutable_key is trusted ingress attestation of the reviewed
                    # bot's timestamp-derived episode key, never legacy key inference.
                    receipt_copies = cast("list[dict[str, object]]", receipt_map["copies"])
                    expected = {(x["chat_id"], x["message_id"]) for x in receipt_copies}
                    payload = {
                        "key": receipt_map["key"],
                        "url": row["url"],
                        "label": LABEL,
                        "revision": row["revision"],
                        "expected_copies": receipt_copies,
                    }
                    status, result = self.request("POST", "/v1/cards/links", json=payload)
                    result_map = cast("dict[str, object]", result)
                    error = CARD_NOT_READY if status in CARD_NOT_READY_STATUSES else BOT_HTTP_ERROR
                    if status == HTTP_OK:
                        updated = {
                            (x.get("chat_id"), x.get("message_id"))
                            for x in cast("list[dict[str, object]]", result_map.get("updated", []))
                        }
                        applied = (
                            result_map.get("key") == receipt_map["key"]
                            and expected <= updated
                            and not result_map.get("pending", [])
                        )
                        ack = {
                            "expected": len(expected),
                            "observed": len(updated),
                            "verified": applied,
                        }
                        error = None if applied else COPIES_PENDING
        except Exception:
            # Ambiguous acceptance is retryable, never a fabricated receipt.
            error = DELIVERY_UNKNOWN
        attempts = cast("int", row["attempts"])
        delay = min(RETRY_DELAY_CAP, 2 ** min(attempts + 1, RETRY_ATTEMPT_CAP)) * (
            RETRY_CLOCK_MIN + RETRY_CLOCK_SPREAD * self.jitter()
        )
        with self.store.db() as c:
            c.execute(
                """UPDATE spi_links SET state=?,error=?,acknowledgement=?,
              available=?,lease=0,owner=NULL WHERE episode=? AND revision=? AND owner=?""",
                (
                    "applied" if applied else "pending",
                    error,
                    json.dumps(ack),
                    self.clock() + (APPLIED_RESCHEDULE if applied else delay),
                    row["episode"],
                    row["revision"],
                    owner,
                ),
            )
            # New desired revision keeps the active lease until old request exits.
            # Its completion must not acknowledge the newer URL, only unblock it.
            c.execute(
                "UPDATE spi_links SET lease=0,owner=NULL WHERE episode=? "
                "AND owner=? AND revision!=?",
                (row["episode"], owner, row["revision"]),
            )
        return True
