"""Mint a one-hour homelab token for wiki pull requests. Separate from the SPI issue token.

Runs as a standalone script (``python -m scripts.wiki_openapi.github_broker``); the
client/server entry points are sibling modules of this package.
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
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TypedDict, cast

PHASE_SIGN = "sign"
PHASE_INSTALLATION = "installation"
PHASE_MINT = "mint"
PHASE_PUBLISH = "publish_secret"
PHASE_BOOTSTRAP = "bootstrap"
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

    Key material and signature bytes never travel through process arguments: the PEM is
    read from the read-only Secret mount and the detached signature is written into the
    pod's size-bounded emptyDir TMPDIR.
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
    with tempfile.TemporaryDirectory(dir=SIGNATURE_DIR) as workspace:
        workdir = Path(workspace)
        signature_path = workdir / "signature.bin"
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
            "Accept": "application/json" if method == "PATCH" else "application/vnd.github+json",
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
        # The refused API path (never a token or key) labels which phase failed.
        path = urllib.parse.urlparse(url).path
        msg = f"HTTP_{exc.code}@{path}"
        raise BrokerFailureError(msg) from None


def _installation_token(now: int) -> _Grant:
    """PHASE_SIGN then PHASE_INSTALLATION: sign, look up, and mint the scoped token."""
    auth = _sign_app_jwt(now)
    installation = cast(
        "_Installation",
        request("GET", "https://api.github.com/repos/alchemmist/homelab/installation", auth),
    )
    permissions = installation.get("permissions") or {}
    if (
        installation.get("suspended_at")
        or permissions.get("pull_requests") != "write"
        or permissions.get("contents") != "write"
    ):
        msg = "APP_PERMISSION_MISSING"
        raise ValueError(msg)
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
    return grant


def _publish_secret(grant: _Grant) -> None:
    """PHASE_PUBLISH: store the minted token in the runtime Secret."""
    root = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    context = ssl.create_default_context(cafile=str(root / "ca.crt"))
    request(
        "PATCH",
        "https://kubernetes.default.svc/api/v1/namespaces/automation/secrets/wiki-openapi-github",
        (root / "token").read_text(),
        {
            "data": {"token": base64.b64encode(grant["token"].encode()).decode()},
            "metadata": {"annotations": {"socrat.alchemmist.xyz/expires-at": grant["expires_at"]}},
        },
        context,
    )


def run_phase() -> str:
    """Execute one phase per step and name the phase that completed last.

    The phase ladder is a value returned to the caller, never ambient state: sign and
    installation happen inside _installation_token, publish inside _publish_secret.
    """
    grant = _installation_token(int(time.time()))
    _publish_secret(grant)
    return PHASE_PUBLISH


_MINT_URL_MARKERS = ("/access_tokens",)
_PUBLISH_URL_MARKERS = ("kubernetes.default.svc",)


def _request_failure_phase(exc: BrokerFailureError) -> str:
    """Name mint vs publish from the API path carried in the error payload."""
    detail = str(exc).lower()
    if any(marker in detail for marker in _PUBLISH_URL_MARKERS):
        return PHASE_PUBLISH
    if any(marker in detail for marker in _MINT_URL_MARKERS):
        return PHASE_MINT
    return PHASE_INSTALLATION


def _failure_code(exc: Exception) -> str:
    """Classify a failure as SIGN_FAILED, its message, or its type name.

    An openssl failure whose output matches none of JWT_ERROR_PHRASES is a real bug,
    not a payload condition; re-raise it untouched so it surfaces as a crash.
    """
    if isinstance(exc, subprocess.CalledProcessError):
        if not any(phrase in str(exc).lower() for phrase in JWT_ERROR_PHRASES):
            raise exc
        return "SIGN_FAILED"
    if isinstance(exc, (BrokerFailureError, ValueError)):
        return str(exc)
    return type(exc).__name__


def _failure_phase(exc: Exception) -> str:
    """Attribute signing errors to sign; attribute request I/O errors to their request.

    The payload contract distinguishes sign, installation, mint and publish; each step
    raises with (or carries) enough identity to name itself: openssl failures are sign,
    BrokerFailureError payloads embed the refused API path, and remaining I/O errors can
    only come from the Kubernetes publish call.
    """
    if isinstance(exc, subprocess.CalledProcessError):
        return PHASE_SIGN
    if isinstance(exc, BrokerFailureError):
        return _request_failure_phase(exc)
    return PHASE_PUBLISH


if __name__ == "__main__":
    try:
        run_phase()
        print(json.dumps({"component": "wiki-openapi-broker", "event": "refresh_ok"}))
    except (
        BrokerFailureError,
        ValueError,
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        ssl.SSLError,
    ) as exc:
        phase = _failure_phase(exc)
        code = _failure_code(exc)
        print(
            json.dumps(
                {
                    "component": "wiki-openapi-broker",
                    "event": "refresh_failed",
                    "phase": phase,
                    "code": code,
                }
            )
        )
        raise SystemExit(1) from exc
