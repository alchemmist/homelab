"""Independent durable-link retry loop; only the native internal bot API is called."""

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from email.message import Message
from typing import IO, Protocol, cast

from telegram_links import Links

# Bot runs on hostNetwork, pinned to socrat-2. Use the exact mesh endpoint
# allowed by the worker NetworkPolicy; do not send the token on redirects.
BASE = "http://10.250.0.2:8082"
CARDS_PATH_PREFIX = "/v1/cards"
CARDS_LINKS_PATH = "/v1/cards/links"
DEFAULT_TIMEOUT = 30
BODY_READ_LIMIT = 2_000_001
BODY_SIZE_LIMIT = 2_000_000
HTTP_OK = 200
# Per-episode persisted backoff shared by discovery and primary backfill.
BACKOFF_MAX_WAIT = 3600
BACKOFF_BASE = 30
BACKOFF_SHIFT_CAP = 7
# Worker loop pacing; one request per tick, never busy-spin.
DISCOVERY_BUSY_WAIT = 1
DISCOVERY_IDLE_WAIT = 30
LOOP_DEFAULT_WAIT = 60
LOOP_MIN_WAIT = 0.1
RETRY_WAIT = 30
MSG_MISSING_BOT_CREDENTIAL = "BOT_LINK_TOKEN_REQUIRED"
MSG_INVALID_BOT_PATH = "INVALID_BOT_PATH"
MSG_BOT_RESPONSE_LIMIT = "BOT_RESPONSE_LIMIT"
REASON_CARD_DISCOVERY_PENDING = "CARD_DISCOVERY_PENDING"
REASON_TARGET_RECOVERY_PENDING = "TARGET_RECOVERY_PENDING"
DISCOVERY_WORKER_NAME = "spi-telegram-discovery"
LINKS_WORKER_NAME = "spi-telegram-links"
RETRY_EVENT = "telegram_link_retry_pending"
COMPONENT = "spi-triage"
HEADER_X_INTERNAL = "X-Internal-Token"
CONTENT_TYPE_HEADER = "Content-Type"
CONTENT_TYPE_JSON = "application/json"


class _StoreHost(Protocol):
    """Durable tables owner: one immediate transaction at a time."""

    def db(self) -> AbstractContextManager[sqlite3.Connection]:
        """Yield the single-writer connection context."""
        ...

    def save(
        self,
        key: str,
        stage: int,
        result: dict[str, object],
        on_save: Callable[[sqlite3.Connection], None] | None = None,
        **fields: object,
    ) -> None:
        """Commit one durable stage checkpoint with reviewed job fields."""
        ...


class _PrimaryHost(Protocol):
    """Read surface of the reviewed primary-publication GitHub reference."""

    def primary_reference(self, marker: str, number: int = 0) -> dict[str, object]:
        """Return the trusted primary publication reference."""
        ...


class Delivery:
    """Original-card delivery worker owning both retry loops and the bot wire."""

    def __init__(self, store: _StoreHost, token: str, *, enabled: bool = False) -> None:
        """Bind the store/token and prepare the durable retry tables."""
        if enabled and not token:
            msg = MSG_MISSING_BOT_CREDENTIAL
            raise ValueError(msg)
        self.store, self.token, self.enabled = store, token, enabled
        self.github: object = None
        self.links = Links(store, self.request, guarded_protocol=enabled)
        self.wake = threading.Event()
        self.discovery_wake = threading.Event()
        self.stopped = threading.Event()
        with store.db() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS spi_card_discovery(episode TEXT PRIMARY KEY,"
                "available REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,error TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS spi_primary_backfill(job_id TEXT PRIMARY KEY,"
                "available REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,error TEXT)"
            )

    def request(self, method: str, path: str, json: object = None) -> tuple[int, object]:
        """Call the native internal bot API with the reviewed path and limits."""
        if not path.startswith(CARDS_PATH_PREFIX) or ".." in path or "://" in path:
            msg = MSG_INVALID_BOT_PATH
            raise ValueError(msg)
        # The json parameter shadows the module; the codec import stays local.
        import json as codec

        body = codec.dumps(json).encode() if json is not None else None

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(
                self,
                _req: urllib.request.Request,
                _fp: IO[bytes],
                _code: int,
                _msg: str,
                _headers: Message,
                _newurl: str,
            ) -> urllib.request.Request | None:
                """Refuse redirects so an attacker cannot relocate the callback."""
                return None

        req = urllib.request.Request(
            BASE + path,
            data=body,
            method=method,
            headers={HEADER_X_INTERNAL: self.token, CONTENT_TYPE_HEADER: CONTENT_TYPE_JSON},
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=DEFAULT_TIMEOUT) as r:
                raw = r.read(BODY_READ_LIMIT)
                if len(raw) > BODY_SIZE_LIMIT:
                    msg = MSG_BOT_RESPONSE_LIMIT
                    raise ValueError(msg)
                return r.status, codec.loads(raw)
        except urllib.error.HTTPError as e:
            return e.code, {}

    def signal(self) -> None:
        """Wake both delivery loops."""
        self.wake.set()
        self.discovery_wake.set()

    def receipt(self, event: dict[str, object], receipt: dict[str, object]) -> bool:
        """Record one external card receipt after checking the episode binding."""
        if (
            receipt.get("episode") != event["episode"]
            or receipt.get("immutable_key") is not True
            or not str(receipt.get("key", "")).endswith("/spi/" + cast("str", event["episode"]))
        ):
            return False
        self.links.record_card_receipt(cast("str", event["episode"]), receipt)
        self.signal()
        return True

    def discover(self) -> bool:
        """Find one eligible episode's original card without blocking the queue."""
        # Separate loop, per-episode persisted backoff, at most one request/tick.
        with self.store.db() as c:
            row = c.execute(
                "SELECT l.episode,coalesce(d.attempts,0) attempts "
                "FROM (SELECT episode FROM spi_links UNION SELECT episode FROM jobs "
                "WHERE state='complete' AND issue>0) l "
                "LEFT JOIN spi_card_receipts r ON r.episode=l.episode "
                "LEFT JOIN spi_card_discovery d ON d.episode=l.episode "
                "WHERE (r.episode IS NULL "
                "OR coalesce(json_array_length(r.receipt,'$.copies'),0)=0) "
                "AND coalesce(d.available,0)<=? "
                "ORDER BY coalesce(d.available,0),l.episode LIMIT 1",
                (time.time(),),
            ).fetchone()
        if row is None:
            return False
        episode = cast("str", row["episode"])
        found = False
        try:
            status, result = self.request("GET", "/v1/cards?status=all&episode=" + episode)
            result_map = cast("dict[str, object]", result)
            cards: list[dict[str, object]] = []
            if status == HTTP_OK:
                cards = cast("list[dict[str, object]]", result_map.get("cards", []))
            if len(cards) == 1:
                card = cards[0]
                copies = [
                    {"chat_id": x["chat_id"], "message_id": x["message_id"]}
                    for x in cast("list[dict[str, object]]", card.get("copies", []))
                    if isinstance(x, dict)
                    and type(x.get("message_id")) is int
                    and cast("int", x.get("message_id")) > 0
                ]
                if copies:
                    found = self.receipt({"episode": episode}, {**card, "copies": copies})
        except Exception:
            pass  # Never block unrelated eligible link deliveries.
        with self.store.db() as c:
            c.execute(
                "INSERT INTO spi_card_discovery VALUES(?,?,?,?) "
                "ON CONFLICT(episode) DO UPDATE SET available=excluded.available,"
                "attempts=excluded.attempts,error=excluded.error",
                (
                    episode,
                    time.time()
                    + min(
                        BACKOFF_MAX_WAIT,
                        BACKOFF_BASE * 2 ** min(row["attempts"], BACKOFF_SHIFT_CAP),
                    ),
                    row["attempts"] + 1,
                    None if found else REASON_CARD_DISCOVERY_PENDING,
                ),
            )
        return True

    def backfill(self) -> bool:
        """Recover trusted primary permalinks for pre-migration completed jobs."""
        # Repeated real alerts may reference pre-migration completed jobs. Recover
        # ONLY their trusted primary permalink; never rerun model/publication.
        if self.github is None:
            return False
        with self.store.db() as c:
            row = c.execute(
                "SELECT j.*,coalesce(b.attempts,0) backfill_attempts FROM jobs j "
                "JOIN spi_card_receipts r ON r.episode=j.episode "
                "LEFT JOIN spi_links l ON l.episode=j.episode "
                "LEFT JOIN spi_primary_backfill b ON b.job_id=j.id "
                "WHERE j.state='complete' AND j.issue>0 "
                "AND coalesce(l.revision,0)<CASE json_extract(j.event,'$.status') "
                "WHEN 'resolved' THEN 2 ELSE 1 END "
                "AND coalesce(b.available,0)<=? "
                "ORDER BY coalesce(b.available,0),j.created DESC LIMIT 1",
                (time.time(),),
            ).fetchone()
        if row is None:
            return False
        found = False
        try:
            github = cast("_PrimaryHost", self.github)
            publication = github.primary_reference(
                "<!-- socrat-spi:" + row["id"] + " -->", row["issue"]
            )
            event = cast("dict[str, object]", json.loads(row["event"]))
            result = cast("dict[str, object]", json.loads(row["result"]))
            result["primary_publication"] = publication

            def queue(c: sqlite3.Connection) -> None:
                """Record the recovered primary within the same save transaction."""
                self.links.record_primary_publication(
                    cast("str", row["id"]),
                    cast("str", row["episode"]),
                    2 if event["status"] == "resolved" else 1,
                    publication,
                    connection=c,
                )

            self.store.save(
                cast("str", row["id"]),
                cast("int", row["stage"]),
                result,
                state="complete",
                on_save=queue,
            )
            found = True
            self.signal()
        except Exception:
            pass  # Never block the next pre-migration recovery candidate.
        with self.store.db() as c:
            c.execute(
                "INSERT INTO spi_primary_backfill VALUES(?,?,?,?) "
                "ON CONFLICT(job_id) DO UPDATE SET available=excluded.available,"
                "attempts=excluded.attempts,error=excluded.error",
                (
                    row["id"],
                    time.time()
                    + min(
                        BACKOFF_MAX_WAIT,
                        BACKOFF_BASE * 2 ** min(row["backfill_attempts"], BACKOFF_SHIFT_CAP),
                    ),
                    row["backfill_attempts"] + 1,
                    None if found else REASON_TARGET_RECOVERY_PENDING,
                ),
            )
        return True

    def _discover_run(self) -> None:
        """Run the discovery/backfill loop until the worker is stopped."""
        while not self.stopped.is_set():
            self.discovery_wake.clear()
            worked = False
            try:
                worked = self.backfill()
                worked = self.discover() or worked
            except Exception:
                worked = False
            self.discovery_wake.wait(DISCOVERY_BUSY_WAIT if worked else DISCOVERY_IDLE_WAIT)

    def _run(self) -> None:
        """Run the durable retry loop, queueing applied rows whose lease expired."""
        while not self.stopped.is_set():
            self.wake.clear()
            timeout = RETRY_WAIT
            try:
                with self.store.db() as c:
                    c.execute(
                        "UPDATE spi_links SET state='pending' "
                        "WHERE state='applied' AND available<=?",
                        (time.time(),),
                    )
                if self.links.once():
                    continue
                with self.store.db() as c:
                    due = c.execute(
                        "SELECT min(max(available,lease)) FROM spi_links WHERE state!='applied'"
                    ).fetchone()[0]
                timeout = (
                    LOOP_DEFAULT_WAIT
                    if due is None
                    else min(LOOP_DEFAULT_WAIT, max(LOOP_MIN_WAIT, due - time.time()))
                )
            except Exception:
                print(json.dumps({"component": COMPONENT, "event": RETRY_EVENT}), flush=True)
                timeout = RETRY_WAIT
            self.wake.wait(timeout)

    def start(self) -> None:
        """Start both delivery threads without blocking the engine."""
        if self.enabled:
            threading.Thread(target=self._run, name=LINKS_WORKER_NAME, daemon=True).start()
            threading.Thread(
                target=self._discover_run, name=DISCOVERY_WORKER_NAME, daemon=True
            ).start()
