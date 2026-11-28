"""Run next to the existing App secret; export ONLY a repo-scoped one-hour token."""

import base64
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import jwt

API_VERSION = "2022-11-28"
APP_PERMISSION_CODE = "APP_PERMISSION_MISSING"
GRANT_SCOPE_CODE = "INVALID_TOKEN_SCOPE"
SERVICE_ACCOUNT_ROOT = "/var/run/secrets/kubernetes.io/serviceaccount"
INSTALLATION_URL = "https://api.github.com/repos/alchemmist/homelab/installation"
GRANT_URL_PREFIX = "https://api.github.com/app/installations/"
GRANT_URL_SUFFIX = "/access_tokens"
CLUSTER_API_URL = (
    "https://kubernetes.default.svc/api/v1/namespaces/automation/secrets/spi-github-installation"
)
EXPIRES_ANNOTATION = "socrat.alchemmist.xyz/expires-at"
REQUEST_TIMEOUT_SECONDS = 25
TOKEN_IAT_SKEW_SECONDS = 30
TOKEN_TTL_SECONDS = 300
LOG_VALID_PHASES = {
    "match",
    "collect",
    "analyze",
    "publish",
    "sign",
    "installation",
    "mint",
    "publish_secret",
    "bootstrap",
}
LOG_ALLOWED_FIELDS = {
    "stage",
    "code",
    "phase",
    "recovered_jobs",
    "oldest_pending_seconds",
    "dead_jobs",
}
LOG_REDACTED = "REDACTED"


def log_event(event: str, level: str = "info", **fields: object) -> None:
    """Print one operational counter line; evidence and IDs never log."""
    # Only operational counters and bounded machine codes, never evidence or IDs.
    allowed = LOG_ALLOWED_FIELDS
    record: dict[str, object] = {key: value for key, value in fields.items() if key in allowed}
    for key in ("stage", "phase", "code"):
        if key in record:
            value = record[key]
            valid = (
                isinstance(value, str) and bool(re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", value))
                if key == "code"
                else value in LOG_VALID_PHASES
            )
            if not valid:
                record[key] = LOG_REDACTED
    record.update(
        ts=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        level=level,
        service="spi-triage",
        component="spi-token-broker",
        event=event,
        msg=event,
    )
    print(json.dumps(record, separators=(",", ":")), flush=True)


class _PhaseLog:
    """Current broker phase for the failure-path log line."""

    phase = "bootstrap"


_PHASE = _PhaseLog()


class BrokerError(Exception):
    """HTTP-level broker failure carrying its machine code."""


def request(
    method: str,
    url: str,
    token: str,
    body: object = None,
    context: ssl.SSLContext | None = None,
) -> object:
    """Issue one reviewed GitHub/Kubernetes API request and return parsed JSON."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json" if method == "PATCH" else "application/vnd.github+json",
            "Content-Type": "application/merge-patch+json"
            if method == "PATCH"
            else "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(
            req, context=context, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        msg = "HTTP_" + str(error.code)
        raise BrokerError(msg) from None


def main() -> None:
    """Mint one repo-scoped installation token into the reviewed Secret."""
    _PHASE.phase = "sign"
    now = int(time.time())
    auth = jwt.encode(
        {
            "iat": now - TOKEN_IAT_SKEW_SECONDS,
            "exp": now + TOKEN_TTL_SECONDS,
            "iss": os.environ["GITHUB_APP_ID"],
        },
        os.environ["GITHUB_PRIVATE_KEY"],
        algorithm="RS256",
    )
    _PHASE.phase = "installation"
    installation = cast("dict[str, object]", request("GET", INSTALLATION_URL, auth))
    permissions = cast("dict[str, object]", installation["permissions"])
    if installation.get("suspended_at") or permissions.get("issues") != "write":
        msg = APP_PERMISSION_CODE
        raise ValueError(msg)
    _PHASE.phase = "mint"
    grant = cast(
        "dict[str, object]",
        request(
            "POST",
            GRANT_URL_PREFIX + str(installation["id"]) + GRANT_URL_SUFFIX,
            auth,
            {
                "repositories": ["homelab"],
                "permissions": {
                    "issues": "write",
                    "contents": "read",
                    "metadata": "read",
                },
            },
        ),
    )
    grant_permissions = cast("dict[str, object]", grant["permissions"])
    if grant_permissions.get("pull_requests") or grant_permissions.get("issues") != "write":
        msg = GRANT_SCOPE_CODE
        raise ValueError(msg)
    root = Path(SERVICE_ACCOUNT_ROOT)
    context = ssl.create_default_context(cafile=str(root / "ca.crt"))
    _PHASE.phase = "publish_secret"
    request(
        "PATCH",
        CLUSTER_API_URL,
        (root / "token").read_text(),
        {
            "data": {"token": base64.b64encode(str(grant["token"]).encode()).decode()},
            "metadata": {"annotations": {EXPIRES_ANNOTATION: str(grant["expires_at"])}},
        },
        context,
    )
    log_event("refresh_ok")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, BrokerError) else type(error).__name__
        log_event("refresh_failed", "error", phase=_PHASE.phase, code=code)
        raise SystemExit(1) from None
