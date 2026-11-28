"""Durable native-card receipts. No Telegram sends or publication side effects.

Call record_receipt with the ORIGINAL pre-redaction alert envelope. The ingress
adapter must use the same source default and normalization as model enqueue.
"""

from core import Failure, Store, normalize

CODE_INVALID_RECEIPT = "INVALID_CARD_RECEIPT"
CODE_INVALID_KEY = "INVALID_CARD_RECEIPT_KEY"
CODE_INVALID_COPIES = "INVALID_CARD_RECEIPT_COPIES"
CODE_INVALID_COPY = "INVALID_CARD_RECEIPT_COPY"
MAX_RECEIPT_KEY_BYTES = 1024
MAX_RECEIPT_COPIES = 1000


def record_receipt(store: Store, payload: object) -> dict[str, object]:
    """Persist one deduplicated native-card receipt for the raw alert identity."""
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise Failure(CODE_INVALID_RECEIPT)
    # Never normalize the redacted job event: fingerprint/labels may differ.
    event = normalize(
        {
            "source": payload.get("source", "socrat-alerts"),
            "alert": payload.get("alert"),
        }
    )
    receipt = payload.get("receipt")
    key: str | None = None
    copies: list[tuple[int, int]] = []
    state = "unknown"
    if isinstance(receipt, dict) and not receipt.get("error"):
        raw_key = receipt.get("key")
        if not isinstance(raw_key, str) or not raw_key or len(raw_key) > MAX_RECEIPT_KEY_BYTES:
            raise Failure(CODE_INVALID_KEY)
        key = raw_key
        raw_copies = receipt.get("copies", [])
        if not isinstance(raw_copies, list) or len(raw_copies) > MAX_RECEIPT_COPIES:
            raise Failure(CODE_INVALID_COPIES)
        # Legacy single-copy response is explicit, not an inferred recipient.
        if not raw_copies and "chat_id" in receipt and "id" in receipt:
            raw_copies = [{"chat_id": receipt["chat_id"], "message_id": receipt["id"]}]
        for copy in raw_copies:
            cursor = copy.get("chat_id") if isinstance(copy, dict) else None
            message = copy.get("message_id") if isinstance(copy, dict) else None
            if type(cursor) is not int or type(message) is not int or message <= 0:
                raise Failure(CODE_INVALID_COPY)
            pair = (cursor, message)
            if pair not in copies:
                copies.append(pair)
        state = "observed" if copies else "unknown"
    # No raw alert, annotations, error text, headers or token is persisted.
    with store.db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS telegram_receipts (
            event_key TEXT NOT NULL, episode TEXT NOT NULL, card_key TEXT NOT NULL,
            chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            PRIMARY KEY(event_key,card_key,chat_id,message_id))"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS telegram_receipt_events (
            event_key TEXT PRIMARY KEY, episode TEXT NOT NULL, status TEXT NOT NULL,
            observed INTEGER NOT NULL DEFAULT 0, unknown INTEGER NOT NULL DEFAULT 0)"""
        )
        c.execute(
            """INSERT INTO telegram_receipt_events VALUES(?,?,?,?,?)
            ON CONFLICT(event_key) DO UPDATE SET
            observed=MAX(observed,excluded.observed), unknown=MAX(unknown,excluded.unknown)""",
            (
                event["event_key"],
                event["episode"],
                event["status"],
                int(state == "observed"),
                int(state == "unknown"),
            ),
        )
        receipt_key = key if key is not None else ""
        for chat, message in copies:
            c.execute(
                "INSERT OR IGNORE INTO telegram_receipts VALUES(?,?,?,?,?)",
                (event["event_key"], event["episode"], receipt_key, chat, message),
            )
    return {
        "event_key": event["event_key"],
        "episode": event["episode"],
        "state": state,
        "copies_observed": len(copies),
    }
