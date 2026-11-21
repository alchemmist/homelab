"""Configure sampling parameters for Open WebUI users via its API."""

import asyncio
import copy
import json
import sqlite3
import urllib.request
from datetime import timedelta
from typing import cast


def _create_admin_token() -> str:
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
    return str(
        create_token(
            {
                "id": admin_id,
                "typ": "session",
                "auth_method": "password",
                "session_stamp": auth.session_stamp,
                "mfa_verified": False,
            },
            timedelta(minutes=5),
        )
    )


def _desired_params(before: dict[str, object]) -> tuple[dict[str, object], dict[str, float]]:
    fields = ("id", "base_model_id", "name", "meta", "params", "access_grants", "is_active")
    desired = {key: copy.deepcopy(before[key]) for key in fields if key in before}
    sampling = {
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
        "presence_penalty": 1.5,
        "repetition_penalty": 1.0,
    }
    params = desired.get("params")
    desired["params"] = {**(params if isinstance(params, dict) else {}), **sampling}
    custom_params = desired["params"].get("custom_params")
    if isinstance(custom_params, dict):
        for key in sampling:
            custom_params.pop(key, None)
    return desired, sampling


def _verify_readback(
    before: dict[str, object], after: dict[str, object], desired: dict[str, object]
) -> None:
    if after["params"] != desired["params"]:
        message = "Qwen sampling settings failed readback validation"
        raise RuntimeError(message)
    for key in ("id", "user_id", "base_model_id", "name", "meta", "is_active"):
        if after.get(key) != before.get(key):
            message = "Unrelated model settings changed"
            raise RuntimeError(message)

    def grants(model: dict[str, object]) -> list[tuple[object, object, object]]:
        return sorted(
            (g.get("principal_type"), g.get("principal_id"), g.get("permission"))
            for g in cast("list[dict[str, object]]", model.get("access_grants") or [])
        )

    if grants(after) != grants(before):
        message = "Model access grants changed"
        raise RuntimeError(message)


def configure():
    'Configure.'
    token = _create_admin_token()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, payload=None):
        req = urllib.request.Request(
            "http://127.0.0.1:8080" + path,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            data=None if payload is None else json.dumps(payload).encode(),
        )
        with opener.open(req, timeout=60) as response:
            return json.load(response)

    if not any(
        model.get("id") == "qwen3.8-27b"
        for model in cast("list[dict[str, object]]", request("/api/v1/models/all"))
    ):
        return {
            "changed": False,
            "skipped": True,
            "reason": "Qwen workspace model is not configured",
        }
    path = "/api/v1/models/model?id=qwen3.8-27b"
    before = cast("dict[str, object]", request(path))
    desired, sampling = _desired_params(before)
    changed = desired["params"] != before.get("params")
    if changed:
        request("/api/v1/models/model/update", desired)
    _verify_readback(before, cast("dict[str, object]", request(path)), desired)
    return {"changed": changed, "model": before["id"], "sampling": sampling}


if __name__ == "__main__":
    print(json.dumps(configure()))
