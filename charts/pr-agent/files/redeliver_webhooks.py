"""Redeliver GitHub App webhook deliveries that never got a response.

GitHub tries a webhook once. PR-Agent only starts a review from pull_request
opened/synchronize, so a timed-out delivery drops the review. Failed deliveries
that share a guid are retried until one of them succeeds, at most three times.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import jwt

API = "https://api.github.com"
INTERESTING = {
    ("pull_request", "opened"),
    ("pull_request", "reopened"),
    ("pull_request", "ready_for_review"),
    ("pull_request", "synchronize"),
    ("issue_comment", "created"),
}
MAX_ATTEMPTS = 3
MIN_AGE_SECONDS = 60
LOOKBACK = 300


def token() -> str:
    now = int(time.time())
    encoded = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": os.environ["GITHUB__APP_ID"].strip()},
        os.environ["GITHUB__PRIVATE_KEY"],
        algorithm="RS256",
    )
    return encoded.decode() if isinstance(encoded, bytes) else encoded


def request(method: str, path: str, bearer: str):
    req = urllib.request.Request(
        API + path,
        method=method,
        headers={
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "pr-agent-webhook-redelivery",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:300]
        raise RuntimeError(f"{method} {path} -> {exc.code} {detail}") from exc


def main() -> None:
    bearer = token()
    deliveries = request("GET", f"/app/hook/deliveries?per_page={LOOKBACK}", bearer)
    grouped: dict[str, list[dict]] = {}
    for delivery in deliveries:
        guid = delivery.get("guid") or str(delivery.get("id"))
        grouped.setdefault(guid, []).append(delivery)

    now = datetime.now(timezone.utc)
    retried = 0
    for guid, attempts in grouped.items():
        if any(item.get("status") == "OK" for item in attempts):
            continue
        latest = max(attempts, key=lambda item: item.get("delivered_at") or "")
        kind = (latest.get("event"), latest.get("action"))
        if kind not in INTERESTING or len(attempts) >= MAX_ATTEMPTS:
            continue
        delivered = datetime.fromisoformat(latest["delivered_at"].replace("Z", "+00:00"))
        if (now - delivered).total_seconds() < MIN_AGE_SECONDS:
            continue
        request("POST", f"/app/hook/deliveries/{latest['id']}/attempts", bearer)
        retried += 1
        print(f"redelivered {kind[0]} {kind[1]} delivery {latest['id']} guid {guid}")
    print(f"redelivered {retried}")


if __name__ == "__main__":
    main()
