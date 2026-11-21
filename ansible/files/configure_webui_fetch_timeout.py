"""Configure the web fetch timeout default for WebUI users via its API."""

import asyncio
import copy
import json
import sqlite3
import urllib.request
from datetime import timedelta
from typing import cast


def configure():
    """Configure."""
    from open_webui.utils.auth import create_token
    from open_webui.utils.mfa import get_auth, get_mfa_config, is_mfa_required

    with sqlite3.connect("file:/app/backend/data/webui.db?mode=ro", uri=True) as db:
        admins = db.execute("SELECT id FROM user WHERE role = 'admin'").fetchall()
    if len(admins) != 1:
        message = "Expected one administrator for local configuration"
        raise RuntimeError(message)
    admin_id = admins[0][0]
    auth = asyncio.run(get_auth(admin_id))
    mfa_config = asyncio.run(get_mfa_config())
    if (auth.mfa and auth.mfa.secret) or is_mfa_required("password", mfa_config):
        message = "An authenticated administrator session is required with MFA"
        raise RuntimeError(message)
    token = create_token(
        {
            "id": admin_id,
            "typ": "session",
            "auth_method": "password",
            "session_stamp": auth.session_stamp,
            "mfa_verified": False,
        },
        timedelta(minutes=5),
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, payload=None) -> dict[str, object]:
        req = urllib.request.Request(
            "http://127.0.0.1:8080" + path,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            data=None if payload is None else json.dumps(payload).encode(),
        )
        with opener.open(req, timeout=60) as response:
            document: dict[str, object] = json.load(response)
            return document

    before = request("/api/v1/retrieval/config")
    desired = copy.deepcopy(before)
    cast("dict[str, object]", desired["web"])["WEB_LOADER_TIMEOUT"] = "15"
    changed = desired != before
    if changed:
        request("/api/v1/retrieval/config/update", {"web": desired["web"]})
    if request("/api/v1/retrieval/config") != desired:
        message = "Web loader timeout failed readback or unrelated settings changed"
        raise RuntimeError(message)
    return {"changed": changed, "web_loader_timeout": "15"}


if __name__ == "__main__":
    print(json.dumps(configure()))
