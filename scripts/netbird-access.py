#!/usr/bin/env python3
"""Audit-first human admission; never creates passwords, peers, setup keys or Kubernetes grants.

Run on the trusted controller with existing private API credentials. All mutation
requires a freshly approved plan hash. User membership actions are additive,
UUID-pinned, and never overwrite other memberships. Uncertain writes stop.
"""

import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import NamedTuple, cast

ADMIN = "netbird-internal-admins"
LEGACY_LOGIN = "netbird-pilot-login"
APP = "netbird-pilot"  # Stable issuer/connector identifier, not a topology label.
PROFILE_MAPPING = "homelab-netbird-profile-groups"
EXPRESSION = 'return {"groups": [group.name for group in request.user.ak_groups.all()]}'


def require(value: object, message: str) -> None:
    """Stop unless the audited invariant holds."""
    if not value:
        raise ValueError(message)


def unique(items: list[object], key: str, value: object) -> dict[str, object]:
    """Return the single reviewed object matching the given key and value."""
    matches = [x for x in items if cast("dict[str, object]", x).get(key) == value]
    require(len(matches) == 1, "Missing or ambiguous reviewed object")
    return cast("dict[str, object]", matches[0])


def safe_group(group: object) -> None:
    """Admission groups must not inherit identity administration."""
    raw = cast("dict[str, object]", group)
    require(
        raw.get("is_superuser") is False and raw.get("parents") == [] and raw.get("roles") == [],
        "Admission group must not inherit identity administration",
    )


class _ReviewedAccount(NamedTuple):
    """The one reviewed NetBird account and its validated JWT settings."""

    account: object
    settings: object


class _ReviewedProvider(NamedTuple):
    """The reviewed OAuth application and its provider identity."""

    app: object
    provider: object


def _require_account_settings(s: object) -> _ReviewedAccount:
    """Require the single reviewed account to run OIDC-only propagation."""
    snapshot = cast("dict[str, object]", s)
    accounts = cast("list[object]", snapshot["nb_accounts"])
    require(len(accounts) == 1, "Exactly one reviewed NetBird account required")
    account = accounts[0]
    settings = cast("dict[str, object]", account)["settings"]
    require(
        cast("dict[str, object]", settings).get("local_auth_disabled") is True
        and cast("dict[str, object]", settings).get("jwt_groups_enabled") is True
        and cast("dict[str, object]", settings).get("groups_propagation_enabled") is True
        and cast("dict[str, object]", settings).get("jwt_groups_claim_name") == "groups",
        "Existing OIDC-only JWT propagation required",
    )
    return _ReviewedAccount(account=account, settings=settings)


def _require_provider_flows(s: object) -> _ReviewedProvider:
    """Require the stable OAuth provider to bind MFA validation with enrollment."""
    snapshot = cast("dict[str, object]", s)
    app = unique(cast("list[object]", snapshot["ak_apps"]), "slug", APP)
    require(
        cast("dict[str, object]", app).get("policy_engine_mode") == "any",
        "Application policy mode drift",
    )
    provider = unique(
        cast("list[object]", snapshot["ak_providers"]),
        "pk",
        cast("dict[str, object]", app)["provider"],
    )
    raw_provider = cast("dict[str, object]", provider)
    require(
        raw_provider.get("sub_mode") == "user_uuid"
        and raw_provider.get("authentication_flow")
        and raw_provider.get("authorization_flow"),
        "Stable UUID subject and authentication flows required",
    )
    stage_ids = {
        cast("dict[str, object]", stage).get("pk") if isinstance(stage, dict) else stage
        for stage in (
            cast("dict[str, object]", binding).get("stage")
            for binding in cast("list[object]", snapshot["ak_flow_bindings"])
        )
    }
    validators = [
        cast("dict[str, object]", stage)
        for stage in cast("list[object]", snapshot["ak_mfa"])
        if cast("dict[str, object]", stage)["pk"] in stage_ids
    ]
    require(
        validators
        and all(
            cast("dict[str, object]", stage).get("not_configured_action") == "configure"
            for stage in validators
        ),
        "Provider authentication flow must bind MFA validation with enrollment, not skip",
    )
    return _ReviewedProvider(app=app, provider=provider)


def _reviewed_profile_scope(s: object) -> object:
    """Require the optional profile mapping to match the reviewed expression."""
    scopes = [
        scope
        for scope in cast("list[object]", cast("dict[str, object]", s)["ak_scopes"])
        if cast("dict[str, object]", scope).get("name") == PROFILE_MAPPING
    ]
    require(len(scopes) <= 1, "Ambiguous NetBird-specific profile mapping")
    scope = scopes[0] if scopes else None
    if scope:
        raw = cast("dict[str, object]", scope)
        require(
            raw.get("scope_name") == "profile" and raw.get("expression") == EXPRESSION,
            "Reviewed profile-scoped genuine groups mapping required",
        )
    return scope


def _effective_admin_rule(s: object, jwt_id: object, all_id: object) -> bool:
    """Require an enabled rule that genuinely sources the admin JWT group."""

    def rule_ids(values: object) -> list[object]:
        return [
            cast("dict[str, object]", v)["id"] if isinstance(v, dict) else v
            for v in cast("list[object]", values or [])
        ]

    admin_rules = 0
    for policy in cast("list[object]", cast("dict[str, object]", s)["nb_policies"]):
        raw_policy = cast("dict[str, object]", policy)
        if not raw_policy.get("enabled"):
            continue
        for raw_rule in cast("list[object]", raw_policy.get("rules") or []):
            rule = cast("dict[str, object]", raw_rule)
            if not rule.get("enabled"):
                continue
            sources = rule_ids(rule.get("sources"))
            destinations = rule_ids(rule.get("destinations"))
            require(
                sources and all_id not in sources and all_id not in destinations,
                "Unreviewed All-device policy; stop before admitting a human",
            )
            admin_rules += jwt_id in sources
    return admin_rules > 0


def _profile_mapping_operations(
    s: object, provider: object, scope: object
) -> list[dict[str, object]]:
    """Plan reviewed profile-mapping creation and provider claim changes."""
    operations: list[dict[str, object]] = []
    if scope is None:
        operations.append(
            {
                "system": "ak",
                "method": "POST",
                "path": "propertymappings/provider/scope/",
                "body": {
                    "name": PROFILE_MAPPING,
                    "scope_name": "profile",
                    "expression": EXPRESSION,
                    "description": "Genuine user groups for NetBird embedded IdP, which requests profile but not groups",
                },
                "purpose": "create-profile-groups-mapping",
                "result_ref": "profile_mapping",
            }
        )
    raw_provider = cast("dict[str, object]", provider)
    mappings = cast("list[object]", raw_provider.get("property_mappings") or [])
    unused = {
        cast("dict[str, object]", p)["pk"]
        for p in cast("list[object]", cast("dict[str, object]", s)["ak_scopes"])
        if cast("dict[str, object]", p).get("name") == "homelab-groups"
        and cast("dict[str, object]", p).get("scope_name") == "groups"
    }
    wanted = [key for key in mappings if key not in unused]
    scope_id = cast("dict[str, object]", scope)["pk"] if scope else "$profile_mapping"
    if scope_id not in wanted:
        wanted.append(scope_id)
    if wanted != mappings:
        operations.append(
            {
                "system": "ak",
                "method": "PATCH",
                "path": "providers/oauth2/" + str(raw_provider["pk"]) + "/",
                "body": {"property_mappings": wanted},
                "purpose": "profile-groups-claim",
            }
        )
    return operations


def _require_valid_bindings(s: object, allowed_ids: object) -> list[object]:
    """Application admission bindings must be enabled group rules only."""
    bindings = cast("list[object]", cast("dict[str, object]", s)["ak_bindings"])
    for binding in bindings:
        raw = cast("dict[str, object]", binding)
        require(
            raw.get("group") in allowed_ids
            and not raw.get("user")
            and not raw.get("policy")
            and raw.get("enabled") is True
            and not raw.get("negate")
            and not raw.get("failure_result"),
            "Unexpected application admission binding; review before changing",
        )
    return bindings


def _admin_admission_operations(
    bindings: list[object], group: object, app: object
) -> list[dict[str, object]]:
    """Plan the missing admin-group application admission binding, if any."""
    raw_group = cast("dict[str, object]", group)
    raw_app = cast("dict[str, object]", app)
    orders = [cast("dict[str, object]", b).get("order", 0) for b in bindings]
    for binding in bindings:
        if cast("dict[str, object]", binding).get("group") == raw_group["pk"]:
            return []
    return [
        {
            "system": "ak",
            "method": "POST",
            "path": "policies/bindings/",
            "body": {
                "target": raw_app["pk"],
                "group": raw_group["pk"],
                "enabled": True,
                "order": max(*orders, 0) + 1,
                "negate": False,
                "failure_result": False,
            },
            "purpose": "admin-application-admission",
        }
    ]


def _trusted_admission_updates(account: object, settings: object) -> list[dict[str, object]]:
    """Plan the trusted-group SSO admission settings updates."""
    operations: list[dict[str, object]] = []
    raw_settings = cast("dict[str, object]", settings)
    allowed = cast("list[str]", raw_settings.get("jwt_allow_groups") or [])
    require(
        allowed and set(allowed).issubset({LEGACY_LOGIN, ADMIN}),
        "Unexpected login allowlist; do not relax approval",
    )
    updated = dict(raw_settings)
    updated["jwt_allow_groups"] = allowed if ADMIN in allowed else allowed + [ADMIN]
    extra = dict(cast("dict[str, object]", raw_settings.get("extra") or {}))
    require(
        extra.get("peer_approval_enabled") is False,
        "Manual peer approval changed; review before claiming automatic device access",
    )
    # IdP group+MFA admission replaces the redundant per-user approval gate.
    extra["user_approval_required"] = False
    updated["extra"] = extra
    raw_account = cast("dict[str, object]", account)
    if updated != raw_settings:
        operations.append(
            {
                "system": "nb",
                "method": "PUT",
                "path": "accounts/" + str(raw_account["id"]),
                "body": {"settings": updated},
                "purpose": "trusted-group-sso-admission",
            }
        )
    return operations


def reconcile_plan(s):
    """Compute the audited infrastructure updates from the reviewed state snapshot."""
    snapshot = cast("dict[str, object]", s)
    reviewed = _require_account_settings(s)
    flows = _require_provider_flows(s)
    scope = _reviewed_profile_scope(s)
    group = unique(cast("list[object]", snapshot["ak_groups"]), "name", ADMIN)
    safe_group(group)
    jwt_group = unique(cast("list[object]", snapshot["nb_groups"]), "name", ADMIN)
    require(
        cast("dict[str, object]", jwt_group).get("issued") == "jwt",
        "Never synthesize an API-issued human source group",
    )
    all_group = unique(cast("list[object]", snapshot["nb_groups"]), "name", "All")
    # A group grant must never silently bless an unrelated Default/All policy.
    require(
        _effective_admin_rule(
            s,
            cast("dict[str, object]", jwt_group)["id"],
            cast("dict[str, object]", all_group)["id"],
        ),
        "No effective policy uses the genuine administrator JWT source",
    )
    operations: list[dict[str, object]] = []
    operations.extend(_profile_mapping_operations(s, flows.provider, scope))
    allowed_ids = {
        cast("dict[str, object]", g)["pk"]
        for g in cast("list[object]", snapshot["ak_groups"])
        if cast("dict[str, object]", g).get("name") in (ADMIN, LEGACY_LOGIN)
    }
    bindings = _require_valid_bindings(s, allowed_ids)
    operations.extend(_admin_admission_operations(bindings, group, flows.app))
    operations.extend(_trusted_admission_updates(reviewed.account, reviewed.settings))
    disabled = cast("dict[str, object]", snapshot["nb_dns"]).get("disabled_management_groups") or []
    if cast("dict[str, object]", all_group)["id"] not in cast("list[object]", disabled):
        operations.append(
            {
                "system": "nb",
                "method": "PUT",
                "path": "dns/settings",
                "body": dict(
                    cast("dict[str, object]", snapshot["nb_dns"]),
                    disabled_management_groups=[
                        *cast("list[object]", disabled),
                        cast("dict[str, object]", all_group)["id"],
                    ],
                ),
                "purpose": "server-side-dns-management-off",
            }
        )
    return operations


def membership_plan(s, username, expected_uuid, revoke=False):
    """Compute grant or revoke operations for one user against a reviewed UUID."""
    require(
        username and expected_uuid,
        "Explicit username and independently reviewed Authentik UUID required",
    )
    user = unique(s["ak_users"], "username", username)
    require(
        user.get("uuid") == expected_uuid
        and (user.get("is_active") is True or (revoke and user.get("is_active") is False)),
        "User UUID/active state mismatch; never substitute email identity",
    )
    require(
        user.get("is_superuser") is False,
        "This workflow admits ordinary humans, not identity administrators",
    )
    require(
        user.get("type") in ("internal", "external"),
        "Service identities are not human admission targets",
    )
    group = unique(s["ak_groups"], "name", ADMIN)
    safe_group(group)
    present = user["pk"] in group.get("users", [])
    if present != revoke:
        return []
    action = "remove_user" if revoke else "add_user"
    return [
        {
            "system": "ak",
            "method": "POST",
            "path": "core/groups/" + group["pk"] + "/" + action + "/",
            "body": {"pk": user["pk"]},
            "purpose": "revoke-human-admission" if revoke else "grant-human-admission",
        }
    ]


def subject_identity(value):
    """Decode Dex's exact protobuf (subject, connector); never match by email."""
    raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
    offset = 0
    fields = []
    for expected_tag in (10, 18):
        require(offset < len(raw) and raw[offset] == expected_tag, "Unexpected subject encoding")
        offset += 1
        size = 0
        shift = 0
        while True:
            require(offset < len(raw) and shift < 21, "Invalid subject size")
            byte = raw[offset]
            offset += 1
            size |= (byte & 127) << shift
            if not byte & 128:
                break
            shift += 7
        require(size > 0 and offset + size <= len(raw), "Invalid subject field")
        fields.append(raw[offset : offset + size].decode())
        offset += size
    require(offset == len(raw), "Unexpected subject suffix")
    return tuple(fields)


def offboard_plan(s, username, expected_uuid):
    """Compute revocation of every reviewed membership for the named user."""
    membership = membership_plan(s, username, expected_uuid, True)
    app = unique(s["ak_apps"], "slug", APP)
    provider = unique(s["ak_providers"], "pk", app["provider"])
    idp = unique(
        [
            p
            for p in s["nb_idps"]
            if p.get("type") == "authentik"
            and p.get("issuer") == "https://auth.socrat.alchemmist.xyz/application/o/" + APP + "/"
            and p.get("client_id") == provider.get("client_id")
        ],
        "type",
        "authentik",
    )
    connector = idp["id"]
    require(connector.startswith("authentik-"), "Unexpected native Authentik connector identifier")
    matches = []
    for user in s["nb_users"]:
        if user.get("is_service_user") or user.get("idp_id") != connector:
            continue
        require(
            subject_identity(user["id"])[1] == connector, "NetBird connector provenance mismatch"
        )
        if subject_identity(user["id"])[0] == expected_uuid:
            matches.append(user)
    require(len(matches) <= 1, "Ambiguous human NetBird subject")
    if not matches:
        return membership
    user = matches[0]
    require(user.get("role") == "user", "Owner/admin NetBird account needs explicit owner review")
    path = "users/" + urllib.parse.quote(user["id"], safe="")
    plan = []
    if not user.get("is_blocked"):
        plan.append(
            {
                "system": "nb",
                "method": "PUT",
                "path": path,
                "body": {
                    "role": "user",
                    "auto_groups": user.get("auto_groups") or [],
                    "is_blocked": True,
                },
                "purpose": "block-human-netbird-login",
            }
        )
    for peer in s["nb_peers"]:
        if peer.get("user_id") == user["id"]:
            plan.append(
                {
                    "system": "nb",
                    "method": "DELETE",
                    "path": "peers/" + urllib.parse.quote(peer["id"], safe=""),
                    "body": None,
                    "purpose": "retire-offboarded-human-device",
                }
            )
    return plan + membership


class API:
    """NetBird and Authentik API client for access checks."""

    def __init__(self, nb_credentials, ak_credentials) -> None:

        self.nb = json.loads(Path(nb_credentials).read_text())["token"]
        self.ak = json.loads(Path(ak_credentials).read_text())["AUTHENTIK_BOOTSTRAP_TOKEN"]

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs) -> None:
                return None

        self.opener = urllib.request.build_opener(NoRedirect)

    def call(self, system, method, path, body=None):
        """Call the Authentik or NetBird API with path validation."""
        require(
            system in ("ak", "nb") and not path.startswith("/") and "://" not in path,
            "Invalid owned API path",
        )
        base, auth = (
            ("https://auth.socrat.alchemmist.xyz/api/v3/", "Bearer " + self.ak)
            if system == "ak"
            else ("https://netbird.socrat.alchemmist.xyz/api/", "Token " + self.nb)
        )
        request = urllib.request.Request(
            base + path,
            method=method,
            headers={
                "Authorization": auth,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            data=None if body is None else json.dumps(body).encode(),
        )
        with self.opener.open(request, timeout=30) as response:
            content = response.read()
            return json.loads(content) if content else None

    def rows(self, path):
        """Collect every paginated row of an API path."""
        result = []
        for page in range(1, 1001):
            data = self.call(
                "ak",
                "GET",
                path + ("&" if "?" in path else "?") + "page_size=100&page=" + str(page),
            )
            result.extend(data["results"])
            if not data.get("pagination", {}).get("next"):
                return result
        raise ValueError("Pagination limit exceeded")

    def snapshot(self):
        """Read the pinned NetBird collections into an inventory snapshot."""
        state = {
            "nb_" + name: self.call("nb", "GET", name)
            for name in ["accounts", "groups", "users", "peers", "policies"]
        }
        state["nb_idps"] = self.call("nb", "GET", "identity-providers")
        state["nb_dns"] = self.call("nb", "GET", "dns/settings")
        for name, endpoint in [
            ("groups", "core/groups/"),
            ("apps", "core/applications/?superuser_full_list=true"),
            ("providers", "providers/oauth2/"),
            ("scopes", "propertymappings/provider/scope/"),
            ("users", "core/users/"),
        ]:
            state["ak_" + name] = self.rows(endpoint)
        app = unique(state["ak_apps"], "slug", APP)
        provider = unique(state["ak_providers"], "pk", app["provider"])
        state["ak_mfa"] = self.rows("stages/authenticator/validate/")
        state["ak_flow_bindings"] = self.rows(
            "flows/bindings/?target=" + provider["authentication_flow"]
        )
        state["ak_bindings"] = self.rows("policies/bindings/?target=" + app["pk"])
        return state


def atomic(path, value):
    """Durably write a JSON value to disk via a temporary file and rename."""
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def check_state_folder(folder):
    """Require a caller-owned private state directory with no unfinished receipts."""
    require(
        folder.is_absolute() and not folder.is_symlink(),
        "Absolute private state directory required",
    )
    if folder.exists():
        info = folder.stat()
        require(
            folder.is_dir() and info.st_uid == os.geteuid() and not info.st_mode & 0o077,
            "State directory must be caller-owned and mode 0700",
        )
        for path in folder.glob("*/receipt.json"):
            require(
                json.loads(path.read_text()).get("state") not in ("applying", "uncertain-stop"),
                "Unfinished mutation receipt; inspect before any rerun",
            )


def build_plan(state, action, username=None, expected_uuid=None):
    """Select and compute the operation plan for the requested action."""
    infrastructure = reconcile_plan(state)
    if action == "reconcile":
        return infrastructure
    require(not infrastructure, "Reconcile admission infrastructure first")
    return (
        offboard_plan(state, username, expected_uuid)
        if action == "offboard"
        else membership_plan(state, username, expected_uuid, action == "revoke")
    )


def main():
    """Run the requested reconciler action against the verified state snapshot."""
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["reconcile", "grant", "revoke", "offboard"])
    parser.add_argument("--username")
    parser.add_argument("--expected-user-uuid")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-plan-hash")
    parser.add_argument(
        "--nb-credentials", default="/var/lib/homelab-netbird-nodes/credential.json"
    )
    parser.add_argument(
        "--ak-credentials", default="/home/alchemmist/.cache/homelab-authentik/credentials.json"
    )
    parser.add_argument("--state-dir", type=Path, default=Path("/var/lib/homelab-netbird-access"))
    args = parser.parse_args()
    check_state_folder(args.state_dir)
    api = API(args.nb_credentials, args.ak_credentials)
    before = api.snapshot()
    plan = build_plan(before, args.action, args.username, args.expected_user_uuid)
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    summary = {
        "action": args.action,
        "apply": args.apply,
        "operations": len(plan),
        "plan_sha256": digest,
        "purposes": [op["purpose"] for op in plan],
    }
    if not args.apply or not plan:
        print(json.dumps(summary))
        return
    require(args.approve_plan_hash == digest, "Approval must match the fresh plan hash")
    args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = os.open(args.state_dir / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    check_state_folder(args.state_dir)
    fresh = api.snapshot()
    require(
        build_plan(fresh, args.action, args.username, args.expected_user_uuid) == plan,
        "Plan drift while acquiring mutation lock; rerun audit",
    )
    before = fresh
    folder = args.state_dir / (
        dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    )
    folder.mkdir(mode=0o700)
    atomic(folder / "before.json", before)
    receipt = {"state": "applying", "plan_sha256": digest, "completed": 0, "plan": plan}
    atomic(folder / "receipt.json", receipt)
    try:
        references = {}
        for operation in plan:
            body = json.loads(json.dumps(operation["body"]))
            if body is not None and "property_mappings" in body:
                body["property_mappings"] = [
                    references.get(value, value) for value in body["property_mappings"]
                ]
                require(
                    "$profile_mapping" not in body["property_mappings"],
                    "Mapping creation not confirmed",
                )
            result = api.call(operation["system"], operation["method"], operation["path"], body)
            if operation.get("result_ref"):
                references["$" + operation["result_ref"]] = result["pk"]
            receipt["completed"] += 1
            atomic(folder / "receipt.json", receipt)
        after = api.snapshot()
        remaining = build_plan(after, args.action, args.username, args.expected_user_uuid)
        require(not remaining, "Post-write readback did not converge")
        atomic(folder / "after.json", after)
        receipt["state"] = "completed"
        atomic(folder / "receipt.json", receipt)
    except Exception:
        receipt["state"] = "uncertain-stop"
        atomic(folder / "receipt.json", receipt)
        raise
    os.close(lock_fd)
    summary["changed"] = True
    print(json.dumps(summary))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as error:
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "error_type": type(error).__name__,
                    "reason": str(error)
                    if isinstance(error, ValueError)
                    else "API/I/O failure; inspect private receipt, no retries",
                }
            )
        )
        sys.exit(1)
