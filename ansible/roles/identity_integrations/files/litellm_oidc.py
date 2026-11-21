#!/usr/bin/env python3
"""Explicit LiteLLM native OIDC rollout. No real password resets or key rotation."""

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import urllib.request
import uuid
from pathlib import Path

HOST = "auth.socrat.alchemmist.xyz"
BASE = "https://" + HOST
OWNER_ID = "socrat-admin"
MAPPING = "homelab-litellm-reviewed-identity"


def identity_expression(owner_uid, owner_email, user_uuids=(), user_group=None):
    # Identities/roles are selected by reviewed immutable subject, never email.
    """Document the identity expression operation."""
    return (
        "uid = str(request.user.uuid)\n"
        'owner = uid.replace("-", "") == ' + repr(owner_uid.replace("-", "")) + "\n"
        "member = uid in "
        + repr(sorted(user_uuids))
        + "\n"
        + (
            (
                "member = member or "
                + repr(user_group)
                + " in [group.name for group in request.user.ak_groups.all()]\n"
            )
            if user_group
            else ""
        )
        + 'return {"litellm_user_id": '
        + repr(OWNER_ID)
        + ' if owner else "authentik:" + uid,\n'
        ' "litellm_user_email": '
        + repr(owner_email)
        + ' if owner else uid + "@sso.socrat.alchemmist.xyz",\n'
        ' "litellm_user_role": "proxy_admin" if owner else ("internal_user" if member else "internal_user_viewer")}\n'
    )


def main():
    """Document the main operation."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--public-edge", default="109.173.40.247")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **kw: original(
        args.public_edge if host == HOST else host, *a, **kw
    )
    os.environ.setdefault("K3S_CONFIG_FILE", "/dev/null")
    kube = ["kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml", "-n", "llm"]
    credentials = json.loads((args.root / "credentials.json").read_text())

    def api(method, path, payload=None):
        req = urllib.request.Request(
            BASE + "/api/v3/" + path,
            method=method,
            headers={
                "Authorization": "Bearer " + credentials["AUTHENTIK_BOOTSTRAP_TOKEN"],
                "Content-Type": "application/json",
            },
            data=json.dumps(payload).encode() if payload is not None else None,
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            return json.loads(body) if body else None

    def kubectl(arguments, data=None):
        r = subprocess.run(kube + arguments, input=data, capture_output=True, timeout=90)
        if r.returncode:
            raise RuntimeError(
                "Kubernetes operation failed; output suppressed to protect credentials"
            )
        return r.stdout

    def private(path, data, overwrite=False):
        if path.exists() and not overwrite:
            return
        with open(path, "w", opener=lambda p, f: os.open(p, f, 0o600)) as out:
            json.dump(data, out, indent=2)
        path.chmod(0o600)

    def one(path, field, value):
        rows = api(
            "GET",
            path
            + "?page_size=100"
            + ("&superuser_full_list=true" if path == "core/applications/" else ""),
        )["results"]
        found = [r for r in rows if r[field] == value]
        if len(found) > 1:
            raise RuntimeError("Ambiguous configuration")
        return found[0] if found else None

    deployment = json.loads(kubectl(["get", "deployment", "litellm", "-o", "json"]))
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    query = """import asyncio,json
from prisma import Prisma
async def main():
 db=Prisma();await db.connect()
 try:
  rows=await db.query_raw('SELECT user_id,user_role,user_email,password,sso_user_id FROM "LiteLLM_UserTable"')
  print(json.dumps(rows,default=str))
 finally:await db.disconnect()
asyncio.run(main())
"""
    raw = kubectl(["exec", "-i", "deployment/litellm", "--", "python", "-"], query.encode())
    users = json.loads(raw.decode().splitlines()[-1])
    _require_versions(api, container)
    owner_rows = _reviewed_rows(users)
    owner = one("core/users/", "username", "alchemmist")
    group = one("core/groups/", "name", "homelab-owner")
    reviewed = json.loads((args.root / "account-mappings.json").read_text())["alchemmist"]
    _require_owner_boundary(owner, group, reviewed)
    granted = _granted_subjects(
        json.loads((args.root / "litellm-users.json").read_text()), owner, one
    )
    access_group = one("core/groups/", "name", "app-litellm-user")
    _require_access_group(access_group)
    if not args.apply:
        print(
            "Preflight passed: native OIDC available, reviewed owner and owner-only local password boundary; no changes"
        )
        return
    private(args.root / "litellm-users-before-oidc.json", users)
    private(args.root / "litellm-deployment-before-oidc.json", deployment)
    _sync_owner_binding(args.root / "litellm-owner-binding.json", private, owner)
    clients = _register_client(args.root / "oidc-clients.json", one, private)
    mapping = _scope_mapping(one, api, owner, owner_rows[0]["user_email"], granted)
    mappings = _default_scope_pks(api) + [mapping["pk"]]
    provider = _require_oauth2_provider(api, one, clients, mappings)
    manifest = json.loads((args.root / "service-icons/sources.json").read_text())
    app = _require_application(api, manifest, provider, one)
    _reconcile_bindings(api, app, group, access_group, granted)
    _reconcile_secret(kubectl, clients, container)


def _require_versions(api: "ApiCall", container: object) -> None:
    """Refuse to run against unreviewed Authentik or LiteLLM versions."""
    if cast("dict[str, object]", api("GET", "admin/version/"))["version_current"] != "2026.8.5":
        raise RuntimeError("Unreviewed Authentik version")
    if cast("dict[str, object]", container)["image"] != "ghcr.io/berriai/litellm:1.105.1":
        raise RuntimeError("Unreviewed LiteLLM version")


def _reviewed_rows(users: "Sequence[dict[str, object]]") -> list[dict[str, object]]:
    """Return the reviewed proxy_admin rows, enforcing the capacity gate."""
    rows = [r for r in users if r["user_id"] == OWNER_ID and r["user_role"] == "proxy_admin"]
    if len(rows) != 1 or len(users) > 5:
        raise RuntimeError("Reviewed owner identity / free-tier capacity gate failed")
    if any(r.get("password") for r in users if r["user_id"] != OWNER_ID):
        raise RuntimeError("Non-owner password identity requires explicit review")
    return rows


def _require_owner_boundary(owner: object, group: object, reviewed: object) -> None:
    """Require the owner account and owner group to match reviewed mappings."""
    if (
        not owner
        or cast("dict[str, object]", owner)["uuid"]
        != cast("dict[str, object]", reviewed).get("idpUserUuid")
        or cast("dict[str, object]", reviewed).get("litellmUserId") != OWNER_ID
    ):
        raise RuntimeError("Owner UUID differs from explicit reviewed account mapping")
    users = cast("list[object]", cast("dict[str, object]", group).get("users", []))
    if not group or cast("dict[str, object]", owner)["pk"] not in users:
        raise RuntimeError("Reviewed owner group boundary missing")


def _granted_subjects(grants: object, owner: object, one: "One") -> list[dict[str, object]]:
    """Verify and return the reviewed internal-user subjects."""
    if not isinstance(grants, dict):
        raise RuntimeError("Invalid reviewed LiteLLM grants")
    granted = []
    for username, grant in cast("dict[str, object]", grants).items():
        entry = cast("dict[str, object]", grant)
        uid = str(uuid.UUID(cast("str", entry["idpUserUuid"])))
        if uid == cast("dict[str, object]", owner)["uuid"] or entry != {
            "idpUserUuid": uid,
            "litellmRole": "internal_user",
        }:
            raise RuntimeError("Unreviewed user privilege or owner override")
        subject = one("core/users/", "username", username)
        if (
            not subject
            or subject["uuid"] != uid
            or not subject["is_active"]
            or subject.get("is_superuser")
        ):
            raise RuntimeError("Reviewed LiteLLM subject missing, inactive, privileged or rebound")
        granted.append(subject)
    if len({u["uuid"] for u in granted}) != len(granted):
        raise RuntimeError("Duplicate LiteLLM subject")
    return granted


def _require_access_group(access_group: object) -> None:
    """Require the reviewed non-privileged LiteLLM app group unchanged."""
    if (
        not access_group
        or cast("dict[str, object]", access_group).get("is_superuser") is not False
        or cast("dict[str, object]", access_group).get("parents") != []
        or cast("dict[str, object]", access_group).get("children") != []
        or cast("dict[str, object]", access_group).get("roles") != []
        or cast("dict[str, object]", access_group).get("attributes") != {"homelab_app_iam": 1}
    ):
        raise RuntimeError("Reviewed non-privileged LiteLLM app group missing or drifted")


def _sync_owner_binding(binding_path: Path, private: "Private", owner: dict[str, object]) -> None:
    """Journal the owner binding, upgrading the initial hashed-UID record."""
    expected_binding = {"authentik_uuid": owner["uuid"], "litellm_user_id": OWNER_ID}
    if binding_path.exists():
        binding = json.loads(binding_path.read_text())
        # One-time upgrade from the initial same-owner hashed UID journal.
        if binding == {"authentik_uid": owner["uid"], "litellm_user_id": OWNER_ID}:
            private(binding_path.parent / "litellm-owner-hashed-uid-original.json", binding)
            private(binding_path, expected_binding, overwrite=True)
        elif binding != expected_binding:
            raise RuntimeError("Owner subject drift; refusing automatic rebind")
    else:
        private(binding_path, expected_binding)


def _register_client(client_path: Path, one: "One", private: "Private") -> dict[str, object]:
    """Return the reviewed client registry, creating the LiteLLM secret if absent."""
    clients = json.loads(client_path.read_text())
    if "litellm" not in clients:
        if one("providers/oauth2/", "name", "homelab-litellm"):
            raise RuntimeError("Existing provider without retained client secret")
        clients["litellm"] = {
            "client_id": "socrat-litellm",
            "client_secret": secrets.token_urlsafe(48),
        }
        private(client_path, clients, overwrite=True)
    return cast("dict[str, object]", clients)


def _scope_mapping(
    one: "One",
    api: "ApiCall",
    owner: dict[str, object],
    owner_email: object,
    granted: list[dict[str, object]],
) -> dict[str, object]:
    """Create or update the reviewed LiteLLM identity scope expression."""
    mapping = one("propertymappings/provider/scope/", "name", MAPPING)
    settings = {
        "name": MAPPING,
        "scope_name": "litellm_identity",
        "expression": identity_expression(
            owner["uuid"],
            owner_email,
            [u["uuid"] for u in granted],
            "app-litellm-user",
        ),
    }
    if not mapping or any(mapping.get(k) != v for k, v in settings.items()):
        updated = api(
            "PATCH" if mapping else "POST",
            "propertymappings/provider/scope/" + (str(mapping["pk"]) + "/" if mapping else ""),
            settings,
        )
        return cast("dict[str, object]", updated)
    return mapping


def _default_scope_pks(api: "ApiCall") -> list[object]:
    """Return the default OpenID/profile/email scope mapping pks in order."""
    scopes = api("GET", "propertymappings/provider/scope/?page_size=100")
    mappings = []
    for scope in ["openid", "profile", "email"]:
        matches = [
            r
            for r in cast("list[dict[str, object]]", cast("dict[str, object]", scopes)["results"])
            if r.get("scope_name") == scope
            and r.get("name") == "authentik default OAuth Mapping: OpenID '" + scope + "'"
        ]
        if len(matches) != 1:
            raise RuntimeError(
                "Missing/ambiguous exact default scope; never mix app profile mappings"
            )
        mappings.append(matches[0]["pk"])
    return mappings


def _require_oauth2_provider(
    api: "ApiCall", one: "One", clients: dict[str, object], mappings: list[object]
) -> dict[str, object]:
    """Create or update the reviewed LiteLLM OAuth2 provider."""
    flows = {
        r["slug"]: r["pk"]
        for r in cast(
            "list[dict[str, object]]",
            cast("dict[str, object]", api("GET", "flows/instances/?page_size=100"))["results"],
        )
    }
    cert = cast(
        "dict[str, object]",
        one("crypto/certificatekeypairs/", "name", "authentik Self-signed Certificate"),
    )
    provider = one("providers/oauth2/", "name", "homelab-litellm")
    client = cast("dict[str, object]", clients["litellm"])
    settings = {
        "name": "homelab-litellm",
        "client_type": "confidential",
        **client,
        "grant_types": ["authorization_code", "refresh_token"],
        "sub_mode": "user_uuid",
        "authentication_flow": flows["default-authentication-flow"],
        "authorization_flow": flows["default-provider-authorization-explicit-consent"],
        "invalidation_flow": flows["default-provider-invalidation-flow"],
        "property_mappings": mappings,
        "signing_key": cert["pk"],
        "redirect_uris": [
            {"matching_mode": "strict", "url": "https://llm.alchemmist.xyz/sso/callback"}
        ],
        "include_claims_in_id_token": True,
        "access_token_validity": "minutes=5",
        "refresh_token_validity": "hours=8",
    }
    return cast(
        "dict[str, object]",
        api(
            "PATCH" if provider else "POST",
            "providers/oauth2/" + (str(provider["pk"]) + "/" if provider else ""),
            settings,
        ),
    )


def _require_application(
    api: "ApiCall", manifest: object, provider: dict[str, object], one: "One"
) -> dict[str, object]:
    """Create or update the reviewed LiteLLM application entry."""
    files = cast("dict[str, object]", cast("dict[str, object]", manifest)["files"])
    sha = cast("str", cast("dict[str, object]", files["litellm.svg"])["sha256"])
    icon = "service-icons/litellm-" + sha[:12] + ".svg"
    app = one("core/applications/", "slug", "litellm")
    settings = {
        "name": "LiteLLM",
        "slug": "litellm",
        "provider": provider["pk"],
        "meta_launch_url": "https://llm.alchemmist.xyz/sso/key/generate",
        "meta_icon": icon,
        "meta_description": "LLM gateway administration. Machine API keys remain separate.",
        "group": "Socrat",
        "policy_engine_mode": "any",
    }
    return cast(
        "dict[str, object]",
        api(
            "PATCH" if app else "POST", "core/applications/" + ("litellm/" if app else ""), settings
        ),
    )


def _reconcile_bindings(
    api: "ApiCall",
    app: dict[str, object],
    group: dict[str, object],
    access_group: dict[str, object],
    granted: list[dict[str, object]],
) -> None:
    """Audit and create the reviewed application admission bindings."""

    def accepted_binding(b: dict[str, object]) -> bool:
        target_ok = (
            b.get("group") in {group["pk"], access_group["pk"]} and b.get("user") is None
        ) or (b.get("group") is None and b.get("user") in {u["pk"] for u in granted})
        return (
            target_ok
            and b.get("policy") is None
            and b.get("enabled") is True
            and b.get("negate") is False
            and b.get("failure_result") is False
            and not b.get("expires")
        )

    bindings = cast(
        "list[dict[str, object]]",
        cast(
            "dict[str, object]",
            api("GET", "policies/bindings/?target=" + str(app["pk"]) + "&page_size=100"),
        )["results"],
    )
    if any(not accepted_binding(b) for b in bindings):
        raise RuntimeError("Unexpected application admission binding; review before rollout")
    if len({(b.get("group"), b.get("user")) for b in bindings}) != len(bindings):
        raise RuntimeError("Duplicate application admission binding")
    if not any(b.get("group") == group["pk"] for b in bindings):
        api(
            "POST",
            "policies/bindings/",
            {
                "target": app["pk"],
                "group": group["pk"],
                "order": 0,
                "enabled": True,
                "failure_result": False,
            },
        )
    if not any(b.get("group") == access_group["pk"] for b in bindings):
        api(
            "POST",
            "policies/bindings/",
            {
                "target": app["pk"],
                "group": access_group["pk"],
                "order": 100,
                "enabled": True,
                "negate": False,
                "failure_result": False,
            },
        )
    for subject in granted:
        if not any(b.get("user") == subject["pk"] for b in bindings):
            api(
                "POST",
                "policies/bindings/",
                {
                    "target": app["pk"],
                    "user": subject["pk"],
                    "order": 90,
                    "enabled": True,
                    "negate": False,
                    "failure_result": False,
                },
            )


def _reconcile_secret(
    kubectl: "Kube", clients: dict[str, object], container: dict[str, object]
) -> None:
    """Apply the LiteLLM OIDC Secret and roll the deployment when changed."""
    import base64

    client = cast("dict[str, object]", clients["litellm"])
    string_data = cast(
        "dict[str, object]",
        {
            "GENERIC_CLIENT_ID": client["client_id"],
            "GENERIC_CLIENT_SECRET": client["client_secret"],
            "GENERIC_AUTHORIZATION_ENDPOINT": BASE + "/application/o/authorize/",
            "GENERIC_TOKEN_ENDPOINT": BASE + "/application/o/token/",
            "GENERIC_USERINFO_ENDPOINT": BASE + "/application/o/userinfo/",
            "GENERIC_SCOPE": "openid profile email litellm_identity",
            "GENERIC_CLIENT_USE_PKCE": "true",
            "GENERIC_USER_ID_ATTRIBUTE": "litellm_user_id",
            "GENERIC_USER_EMAIL_ATTRIBUTE": "litellm_user_email",
            "GENERIC_USER_ROLE_ATTRIBUTE": "litellm_user_role",
            "PROXY_BASE_URL": "https://llm.alchemmist.xyz",
        },
    )
    secret: dict[str, object] = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "socrat-authentik-litellm", "namespace": "llm"},
        "type": "Opaque",
        "stringData": string_data,
    }

    old = kubectl(["get", "secret", "socrat-authentik-litellm", "--ignore-not-found", "-o", "json"])
    old_data = cast("dict[str, object]", json.loads(old).get("data", {})) if old else {}
    changed_secret = any(
        old_data.get(k) != base64.b64encode(str(v).encode()).decode()
        for k, v in string_data.items()
    )
    kubectl(["apply", "-f", "-"], json.dumps(secret).encode())
    env_from = cast("list[dict[str, object]]", container.get("envFrom", []))
    has_mount = any(
        cast("dict[str, object]", e.get("secretRef", {})).get("name") == "socrat-authentik-litellm"
        for e in env_from
    )
    if not has_mount or changed_secret:
        if not has_mount:
            env_from = [*env_from, {"secretRef": {"name": "socrat-authentik-litellm"}}]
        patch: dict[str, object] = {
            "spec": {
                "template": {
                    "spec": {"containers": [{"name": container["name"], "envFrom": env_from}]}
                }
            }
        }
        template = cast("dict[str, object]", cast("dict[str, object]", patch["spec"])["template"])
        template["metadata"] = {
            "annotations": {
                "socrat.alchemmist.xyz/oidc-env-sha256": hashlib.sha256(
                    json.dumps(string_data, sort_keys=True).encode()
                ).hexdigest()
            }
        }
        kubectl(["patch", "deployment", "litellm", "--type=strategic", "-p", json.dumps(patch)])
        print(
            "Native OIDC configured; graceful rolling update started. Do not force-delete draining pods."
        )
    else:
        print("Native OIDC configuration reconciled; no deployment restart requested")


class One(Protocol):
    """Callable matching the in-main `one` lookup helper."""

    def __call__(self, path: str, field: str, value: str) -> dict[str, object] | None:
        """Return the unique reviewed Authentik record, if present."""
        ...


class ApiCall(Protocol):
    """Callable matching the in-main `api` Authentik HTTP helper."""

    def __call__(self, method: str, path: str, payload: object | None = ...) -> object:
        """Perform one reviewed Authentik API call."""
        ...


class Kube(Protocol):
    """Callable matching the in-main `kubectl` command helper."""

    def __call__(self, arguments: list[str], data: object | None = ...) -> bytes:
        """Run one reviewed kubectl invocation, returning its stdout."""
        ...


class Private(Protocol):
    """Callable matching the in-main `private` journal writer."""

    def __call__(self, path: Path, data: object, *, overwrite: bool = ...) -> None:
        """Persist one 0600-reviewed JSON artifact."""
        ...


if __name__ == "__main__":
    main()
