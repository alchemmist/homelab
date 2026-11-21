"""Configure web search/SearXNG settings for Open WebUI users."""

import asyncio
import copy
import json
import sqlite3
import urllib.request
from datetime import timedelta
from typing import Protocol, cast


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


class Request(Protocol):
    """JSON request helper used by the Open WebUI configuration steps."""

    def __call__(self, path: str, payload: object | None = None) -> object:
        """Issue a JSON request against the local Open WebUI instance."""
        ...


def _apply_web_settings(request: Request) -> bool:
    web_settings = {
        "ENABLE_WEB_SEARCH": True,
        "WEB_SEARCH_ENGINE": "searxng",
        "SEARXNG_QUERY_URL": "http://searxng.llm.svc.cluster.local:8080/search?q=<query>&format=json",
    }
    retrieval = cast("dict[str, dict[str, object]]", request("/api/v1/retrieval/config"))
    web_changed = any(retrieval["web"].get(key) != value for key, value in web_settings.items())
    if web_changed:
        request("/api/v1/retrieval/config/update", {"web": {**retrieval["web"], **web_settings}})
    after_retrieval = request("/api/v1/retrieval/config")
    expected_retrieval = copy.deepcopy(retrieval)
    expected_retrieval["web"].update(web_settings)
    if after_retrieval != expected_retrieval:
        message = "Unrelated retrieval settings changed"
        raise RuntimeError(message)
    if any(
        cast("dict[str, dict[str, object]]", after_retrieval)["web"].get(key) != value
        for key, value in web_settings.items()
    ):
        message = "Web search configuration failed readback validation"
        raise RuntimeError(message)
    return web_changed


def _apply_default_permissions(request: Request) -> tuple[bool, dict[str, object]]:
    permissions = cast("dict[str, object]", request("/api/v1/users/default/permissions"))
    desired_permissions = copy.deepcopy(permissions)
    features_or_none = desired_permissions.setdefault("features", {})
    cast("dict[str, object]", features_or_none)["web_search"] = True
    permissions_changed = desired_permissions != permissions
    if permissions_changed:
        request("/api/v1/users/default/permissions", desired_permissions)
    if request("/api/v1/users/default/permissions") != desired_permissions:
        message = "User search permissions failed readback validation"
        raise RuntimeError(message)
    return permissions_changed, desired_permissions


def _apply_model_settings(request: Request) -> tuple[bool, dict[str, object], dict[str, object]]:
    path = "/api/v1/models/model?id=qwen3.8-27b"
    before = cast("dict[str, object]", request(path))
    fields = ("id", "base_model_id", "name", "meta", "params", "access_grants", "is_active")
    desired = {key: copy.deepcopy(before[key]) for key in fields if key in before}
    meta = cast("dict[str, object]", desired.get("meta") or {})
    desired["meta"] = meta
    capabilities = meta.get("capabilities")
    meta["capabilities"] = {
        **(capabilities if isinstance(capabilities, dict) else {}),
        "web_search": True,
    }
    feature_block = meta.get("defaultFeatureIds")
    meta["defaultFeatureIds"] = [
        *dict.fromkeys([*(feature_block if isinstance(feature_block, list) else []), "web_search"])
    ]
    params = desired.get("params")
    desired["params"] = {
        **(params if isinstance(params, dict) else {}),
        "function_calling": "native",
    }
    public_read: dict[str, object] = {
        "principal_type": "user",
        "principal_id": "*",
        "permission": "read",
    }
    grants = cast("list[dict[str, object]]", desired.get("access_grants") or [])
    desired["access_grants"] = grants
    if not any(
        all(grant.get(key) == value for key, value in public_read.items()) for grant in grants
    ):
        grants.append(public_read)
    model_changed = any(
        desired.get(key) != before.get(key) for key in ("meta", "params", "access_grants")
    )
    if model_changed:
        request("/api/v1/models/model/update", desired)
    after = cast("dict[str, object]", request(path))
    if after["meta"] != desired["meta"] or after["params"] != desired["params"]:
        message = "Qwen search settings failed readback validation"
        raise RuntimeError(message)
    for key in ("id", "user_id", "base_model_id", "name", "is_active"):
        if after.get(key) != before.get(key):
            message = "Unrelated model settings changed"
            raise RuntimeError(message)

    def grant_key(model: dict[str, object]) -> list[tuple[object, object, object]]:
        return sorted(
            (g.get("principal_type"), g.get("principal_id"), g.get("permission"))
            for g in cast("list[dict[str, object]]", model.get("access_grants") or [])
        )

    if grant_key(after) != grant_key(desired):
        message = "Model access grants changed"
        raise RuntimeError(message)
    return model_changed, before, after


async def _verify_users(desired_permissions: dict[str, object], after_access_grants: object) -> int:
    from open_webui.utils.access_control import has_permission, has_access

    with sqlite3.connect("file:/app/backend/data/webui.db?mode=ro", uri=True) as db:
        users = db.execute("SELECT id FROM user WHERE role IN ('admin', 'user')").fetchall()
    for (user_id,) in users:
        if not await has_permission(user_id, "features.web_search", desired_permissions):
            message = "A user does not have web search permission"
            raise RuntimeError(message)
        if not await has_access(user_id, "read", after_access_grants):
            message = "A user does not have Qwen model access"
            raise RuntimeError(message)
    return len(users)


def configure():
    'Configure.'
    token = _create_admin_token()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path: str, payload: object | None = None) -> object:
        req = urllib.request.Request(
            "http://127.0.0.1:8080" + path,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            data=None if payload is None else json.dumps(payload).encode(),
        )
        with opener.open(req, timeout=60) as response:
            return json.load(response)

    web_changed = _apply_web_settings(request)
    permissions_changed, desired_permissions = _apply_default_permissions(request)
    model_changed, before, after = _apply_model_settings(request)
    user_count = asyncio.run(_verify_users(desired_permissions, after["access_grants"]))
    return {
        "changed": web_changed or permissions_changed or model_changed,
        "engine": "searxng",
        "model": before["id"],
        "users_verified": user_count,
    }


if __name__ == "__main__":
    print(json.dumps(configure()))  # noqa: T201
