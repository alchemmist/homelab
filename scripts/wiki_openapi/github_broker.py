"""Mint a one-hour homelab token for wiki pull requests. Separate from the SPI issue token.

Runs as a standalone script (``python scripts/wiki_openapi/github_broker.py``);
the client/server entry points are sibling modules resolved through ``sys.path``.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import TypedDict, cast

PHASE = "bootstrap"
PRIVATE_KEY_PATH = "/var/run/secrets/github-app/private-key"
SIGNATURE_DIR = os.environ["TMPDIR"]
JWT_ERROR_PHRASES = ("jwt", "signature", "algor")
_CLOCK_SKEW_SECONDS = 30
_TOKEN_LIFETIME_SECONDS = 300


class BrokerFailureError(Exception):
    """Exception raised when the wiki broker run fails."""


class _Installation(TypedDict):
    id: int
    suspended_at: str | None
    permissions: dict[str, str]


class _Grant(TypedDict):
    token: str
    expires_at: str
    permissions: dict[str, str]


def _b64url(raw: bytes) -> str:
    """Base64url-encode without padding, as JWS requires."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _sign_app_jwt(now: int) -> str:
    """Sign the installation JWT with the in-image openssl CLI. PyJWT is not packaged.

    The PEM arrives on the read-only Secret mount and the detached signature is written
    into the pod's size-bounded emptyDir TMPDIR; neither key material nor signature
    bytes ever travel through process arguments.
    """
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64url(
        json.dumps(
            {
                "iat": now - _CLOCK_SKEW_SECONDS,
                "exp": now + _TOKEN_LIFETIME_SECONDS,
                "iss": os.environ["GITHUB_APP_ID"],
            }
        ).encode()
    )
    payload = header + "." + claims
    signature_path = Path(
        tempfile.mkstemp(prefix="wiki-broker-sig-", dir=SIGNATURE_DIR)[1]
    )
    try:
        subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                PRIVATE_KEY_PATH,
                "-out",
                str(signature_path),
            ],
            input=payload.encode(),
            capture_output=True,
            check=True,
        )
        signature = signature_path.read_bytes()
    finally:
        with suppress(OSError):
            signature_path.unlink(missing_ok=True)
    if not signature:
        msg = "EMPTY_SIGNATURE"
        raise BrokerFailureError(msg)
    return payload + "." + _b64url(signature)


def request(
    method: str,
    url: str,
    token: str,
    body: object = None,
    context: ssl.SSLContext | None = None,
) -> object:
    """Send one GitHub API request and decode the JSON reply."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json"
            if method == "PATCH"
            else "application/vnd.github+json",
            "Content-Type": "application/merge-patch+json"
            if method == "PATCH"
            else "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, context=context, timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise BrokerFailureError("HTTP_" + str(exc.code)) from None


def main() -> None:
    """Mint the one-hour token and publish it to the runtime Secret."""
    global PHASE  # noqa: PLW0603 - phase labels the published failure payload
    PHASE = "sign"
    now = int(time.time())
    auth = _sign_app_jwt(now)
    PHASE = "installation"
    installation = cast(
        "_Installation",
        request(
            "GET", "https://api.github.com/repos/alchemmist/homelab/installation", auth
        ),
    )
    permissions = installation.get("permissions") or {}
    if (
        installation.get("suspended_at")
        or permissions.get("pull_requests") != "write"
        or permissions.get("contents") != "write"
    ):
        msg = "APP_PERMISSION_MISSING"
        raise ValueError(msg)
    PHASE = "mint"
    grant = cast(
        "_Grant",
        request(
            "POST",
            "https://api.github.com/app/installations/"
            + str(installation["id"])
            + "/access_tokens",
            auth,
            {
                "repositories": ["homelab"],
                "permissions": {
                    "contents": "write",
                    "pull_requests": "write",
                    "metadata": "read",
                },
            },
        ),
    )
    granted = grant["permissions"]
    if (
        granted.get("contents") != "write"
        or granted.get("pull_requests") != "write"
        or granted.get("issues")
    ):
        msg = "INVALID_TOKEN_SCOPE"
        raise ValueError(msg)
    root = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    context = ssl.create_default_context(cafile=str(root / "ca.crt"))
    PHASE = "publish_secret"
    request(
        "PATCH",
        "https://kubernetes.default.svc/api/v1/namespaces/automation/secrets/wiki-openapi-github",
        (root / "token").read_text(),
        {
            "data": {"token": base64.b64encode(grant["token"].encode()).decode()},
            "metadata": {
                "annotations": {"socrat.alchemmist.xyz/expires-at": grant["expires_at"]}
            },
        },
        context,
    )
    print(json.dumps({"component": "wiki-openapi-broker", "event": "refresh_ok"}))


if __name__ == "__main__":
    try:
        main()
    except (
        BrokerFailureError,
        ValueError,
        OSError,
        KeyError,
        subprocess.CalledProcessError,
        ssl.SSLError,
    ) as exc:
        detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError) and not any(
            phrase in detail.lower() for phrase in JWT_ERROR_PHRASES
        ):
            raise  # a failed openssl call unrelated to signing is a real bug
        code = (
            str(exc)
            if isinstance(exc, (BrokerFailureError, ValueError))
            else type(exc).__name__
        )
        print(
            json.dumps(
                {
                    "component": "wiki-openapi-broker",
                    "event": "refresh_failed",
                    "phase": PHASE,
                    "code": code,
                }
            )
        )
        raise SystemExit(1) from exc
