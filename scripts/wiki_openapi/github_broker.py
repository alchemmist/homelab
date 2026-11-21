"""Mint a one-hour homelab token for wiki pull requests. Separate from the SPI issue token."""

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import jwt

PHASE = "bootstrap"


class BrokerFailure(Exception):
    pass


def request(
    method: str,
    url: str,
    token: str,
    body: object = None,
    context: ssl.SSLContext | None = None,
) -> dict[str, object]:
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
            value: dict[str, object] = json.load(response)
            return value
    except urllib.error.HTTPError as exc:
        raise BrokerFailure("HTTP_" + str(exc.code)) from None


def main() -> None:
    global PHASE
    PHASE = "sign"
    now = int(time.time())
    auth = jwt.encode(
        {"iat": now - 30, "exp": now + 300, "iss": os.environ["GITHUB_APP_ID"]},
        os.environ["GITHUB_PRIVATE_KEY"],
        algorithm="RS256",
    )
    PHASE = "installation"
    installation = request(
        "GET", "https://api.github.com/repos/alchemmist/homelab/installation", auth
    )
    permissions = installation.get("permissions") or {}
    if not isinstance(permissions, dict):
        reason = "APP_PERMISSION_MISSING"
        raise TypeError(reason)
    if (
        installation.get("suspended_at")
        or permissions.get("pull_requests") != "write"
        or permissions.get("contents") != "write"
    ):
        reason = "APP_PERMISSION_MISSING"
        raise TypeError(reason)
    PHASE = "mint"
    grant = request(
        "POST",
        "https://api.github.com/app/installations/" + str(installation["id"]) + "/access_tokens",
        auth,
        {
            "repositories": ["homelab"],
            "permissions": {"contents": "write", "pull_requests": "write", "metadata": "read"},
        },
    )
    granted = grant["permissions"]
    if not isinstance(granted, dict):
        reason = "INVALID_TOKEN_SCOPE"
        raise TypeError(reason)
    if (
        granted.get("contents") != "write"
        or granted.get("pull_requests") != "write"
        or granted.get("issues")
    ):
        reason = "INVALID_TOKEN_SCOPE"
        raise TypeError(reason)
    root = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    context = ssl.create_default_context(cafile=str(root / "ca.crt"))
    PHASE = "publish_secret"
    request(
        "PATCH",
        "https://kubernetes.default.svc/api/v1/namespaces/automation/secrets/wiki-openapi-github",
        (root / "token").read_text(),
        {
            "data": {"token": base64.b64encode(str(grant["token"]).encode()).decode()},
            "metadata": {"annotations": {"socrat.alchemmist.xyz/expires-at": grant["expires_at"]}},
        },
        context,
    )
    print(json.dumps({"component": "wiki-openapi-broker", "event": "refresh_ok"}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, (BrokerFailure, ValueError)) else type(exc).__name__
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
        raise SystemExit(1)
