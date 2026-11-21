"""Existing-user app membership lifecycle. Default plan/check are GET-only.
Never creates/deletes/merges humans, resets passwords/MFA or manages legacy groups.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from app_iam import (
    admission_groups,
    app_groups,
    rows,
    validate_bindings,
    validate_group,
)

BASE = "https://auth.socrat.alchemmist.xyz/api/v3/"
OWNER = "alchemmist"


class Api(Protocol):
    """Callable Authentik v3 client bound to the deployment token."""

    def __call__(
        self, method: str, endpoint: str, payload: object | None = ...
    ) -> dict[str, object] | None:
        """Perform the API request and return the parsed response body."""


def api_for(root: Path) -> Api:
    'Api for.'
    path = root / "credentials.json"
    if root.stat().st_mode & 0o077 or path.stat().st_mode & 0o077:
        raise RuntimeError("Deployment directory/credentials must be private")
    token = cast(
        "str", cast("dict[str, object]", json.loads(path.read_text()))["AUTHENTIK_BOOTSTRAP_TOKEN"]
    )

    def api(method: str, endpoint: str, payload: object | None = None) -> dict[str, object] | None:
        req = urllib.request.Request(
            BASE + endpoint,
            method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            data=json.dumps(payload).encode() if payload is not None else None,
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            body = response.read()
            return json.loads(body) if body else None

    return api


def unique(items: list[dict[str, object]], field: str) -> dict[object, dict[str, object]]:
    """Index live objects by a key, refusing ambiguous duplicates."""
    result = {}
    for item in items:
        if item[field] in result:
            raise RuntimeError("Ambiguous live object")
        result[item[field]] = item
    return result


def _require_declared(declared: set[str], groups: dict[object, dict[str, object]]) -> None:
    """Fail unless every declared catalog group already exists and is reviewed."""
    for name in declared:
        if name not in groups:
            raise RuntimeError("Missing app group; deploy foundation first: " + name)
        validate_group(groups[name])


def _verify_applications(
    api: Api,
    services: dict[str, object],
    groups: dict[object, dict[str, object]],
    applications: dict[object, dict[str, object]],
) -> None:
    """Verify each generic SSO application exists with its admission bindings."""
    for slug, raw in services.items():
        service = cast("dict[str, object]", raw)
        # Portal-only apps and subject-only integrations do not become generic SSO.
        if service.get("managedBy") or not service.get("appRoles"):
            continue
        app = applications.get(slug)
        if not app or app.get("policy_engine_mode") != "any":
            raise RuntimeError("Missing application or admission mode drift: " + slug)
        allowed = admission_groups(slug, service)
        if any(n not in groups for n in allowed):
            raise RuntimeError("Missing legacy admission group")
        actual = validate_bindings(
            rows(api, "policies/bindings/?target=" + str(app["pk"])),
            {groups[n]["pk"] for n in allowed},
        )
        if actual != {groups[n]["pk"] for n in allowed}:
            raise RuntimeError("Missing admission binding: " + slug)


def _validated_user(
    name: str,
    desired: dict[str, object],
    live: dict[object, dict[str, object]],
    reviewed: dict[str, object],
    seen_uuids: set[str],
) -> dict[str, object]:
    """Validate one manifest entry and return the matching exact live user."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
        raise RuntimeError("Invalid username")
    if set(desired) != {"uuid", "state", "appGroups"}:
        raise RuntimeError("Unsupported user schema: " + name)
    try:
        UUID(cast("str", desired["uuid"]))
    except (ValueError, TypeError, AttributeError):
        raise RuntimeError("Invalid reviewed UUID") from None
    if desired["uuid"] in seen_uuids:
        raise RuntimeError("Duplicate UUID")
    seen_uuids.add(cast("str", desired["uuid"]))
    user = live.get(name)
    if not user or user["uuid"] != desired["uuid"]:
        raise RuntimeError("Exact existing username/UUID required: " + name)
    reviewed_entry = reviewed.get(name)
    if isinstance(reviewed_entry, dict) and user["uuid"] != reviewed_entry.get("idpUserUuid"):
        raise RuntimeError("Reviewed subject changed: " + name)
    if user.get("type", "internal") != "internal":
        raise RuntimeError("Human lifecycle refuses service/external accounts")
    return user


def _validated_state(desired: dict[str, object], declared: set[str]) -> tuple[str, list[str]]:
    """Validate and return the declared lifecycle state and app group list."""
    state = cast("str", desired["state"])
    wanted = desired["appGroups"]
    if state not in ("preserve", "active", "disabled") or not isinstance(wanted, list):
        raise RuntimeError("Invalid lifecycle state/groups")
    groups = cast("list[str]", wanted)
    if len(set(groups)) != len(groups) or any(g not in declared for g in groups):
        raise RuntimeError("Only declared app groups may be managed")
    if state == "disabled" and groups:
        raise RuntimeError("Disabled users must have empty appGroups")
    return state, groups


def _require_known_membership(
    user: dict[str, object], pk_to_group: dict[object, str], declared: set[str]
) -> set[str]:
    """Return current managed groups, refusing unknown app membership."""
    current = {pk_to_group[g] for g in cast("list[object]", user["groups"]) if g in pk_to_group}
    unknown = [
        pk_to_group[g]
        for g in cast("list[object]", user["groups"])
        if g in pk_to_group and pk_to_group[g].startswith("app-") and pk_to_group[g] not in declared
    ]
    if unknown:
        raise RuntimeError("Unknown app membership requires separate controller review")
    return current


def _require_assignable(added: set[str], declared: dict[str, dict[str, object]]) -> None:
    """Refuse assignments into groups whose native authorization is not ready."""
    if any(not declared[g]["assignable"] for g in added):
        raise RuntimeError("Native authorization not ready; group assignment blocked")


def _require_unprotected(
    name: str,
    user: dict[str, object],
    desired: dict[str, object],
    managed: set[str],
    current: set[str],
) -> None:
    """Refuse owner-destroying or elevation-adjacent changes."""
    state = cast("str", desired["state"])
    wanted = cast("list[str]", desired["appGroups"])
    if name == OWNER and (state != "preserve" or set(wanted) != managed):
        raise RuntimeError("Owner state/membership is protected")
    if name != OWNER and (user.get("is_superuser") or "homelab-owner" in current):
        raise RuntimeError("Human lifecycle refuses elevated identity")


def _user_operations(
    name: str,
    user: dict[str, object],
    desired: dict[str, object],
    declared: dict[str, dict[str, object]],
    catalog: tuple[dict[object, dict[str, object]], dict[object, str]],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Snapshot the user and compute membership/state operations."""
    groups, pk_to_group = catalog
    state, wanted = _validated_state(desired, set(declared))
    current = _require_known_membership(user, pk_to_group, set(declared))
    managed = current & set(declared)
    added = set(wanted) - managed
    _require_assignable(added, declared)
    _require_unprotected(name, user, desired, managed, current)
    snapshot: dict[str, object] = {
        "username": name,
        "uuid": user["uuid"],
        "pk": user["pk"],
        "active": user["is_active"],
        "groups": sorted(cast("list[str]", user["groups"])),
    }
    operations: list[dict[str, object]] = []
    # Disable FIRST, before membership removals. Never enable on preserve.
    if state == "disabled" and user["is_active"]:
        operations.append({"action": "disable", "username": name, "pk": user["pk"]})
    for group in sorted(managed - set(wanted)):
        operations.append(
            {
                "action": "remove",
                "username": name,
                "pk": user["pk"],
                "group": group,
                "groupPk": groups[group]["pk"],
            }
        )
    for group in sorted(added):
        operations.append(
            {
                "action": "add",
                "username": name,
                "pk": user["pk"],
                "group": group,
                "groupPk": groups[group]["pk"],
            }
        )
    if state == "active" and not user["is_active"]:
        operations.append({"action": "enable", "username": name, "pk": user["pk"]})
    return snapshot, operations


def build_plan(
    api: Api,
    services: dict[str, object],
    manifest: dict[str, object],
    reviewed: dict[str, object],
) -> dict[str, object]:
    """Compute a reviewed lifecycle plan: validated reads only, no writes."""
    if set(manifest) != {"version", "users"} or manifest["version"] != 1:
        raise RuntimeError("Unsupported lifecycle schema")
    declared = app_groups(services)
    groups = unique(rows(api, "core/groups/"), "name")
    _require_declared(set(declared), groups)
    applications = unique(rows(api, "core/applications/?superuser_full_list=true"), "slug")
    _verify_applications(api, services, groups, applications)
    live = unique(rows(api, "core/users/"), "username")
    pk_to_group: dict[object, str] = {
        g["pk"]: name for name, g in cast("dict[str, dict[str, object]]", groups).items()
    }
    operations = []
    snapshot = []
    seen_uuids: set[str] = set()
    for name, desired in sorted(cast("dict[str, dict[str, object]]", manifest["users"]).items()):
        user = _validated_user(name, desired, live, reviewed, seen_uuids)
        entry, ops = _user_operations(
            name,
            user,
            desired,
            cast("dict[str, dict[str, object]]", declared),
            (groups, pk_to_group),
        )
        snapshot.append(entry)
        operations.extend(ops)
    # Hash covers reviewed input + complete current membership/state, not only writes.
    context = {
        "manifest": manifest,
        "services": services,
        "reviewed": reviewed,
        "snapshot": snapshot,
        "operations": operations,
    }
    digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    return {
        "sha256": digest,
        "operations": operations,
        "limits": "IdP state and app groups only; native sessions, tokens and legacy grants require separate revocation",
    }


def apply_plan(api: Api, plan: dict[str, object], approval: object) -> None:
    """Apply an approved lifecycle plan; every operation is idempotent."""
    if approval != plan["sha256"]:
        raise RuntimeError("Plan approval hash mismatch; review a fresh plan")
    for operation in cast("list[dict[str, object]]", plan["operations"]):
        if operation["action"] in ("disable", "enable"):
            api(
                "PATCH",
                "core/users/" + str(operation["pk"]) + "/",
                {"is_active": operation["action"] == "enable"},
            )
        else:
            api(
                "POST",
                "core/groups/"
                + str(operation["groupPk"])
                + "/"
                + ("add_user/" if operation["action"] == "add" else "remove_user/"),
                {"pk": operation["pk"]},
            )


def main():
    'Main.'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("action", choices=["plan", "check", "apply"], default="plan", nargs="?")
    parser.add_argument("--approve-sha256")
    args = parser.parse_args()
    root = args.root
    # A local lock serializes THIS lifecycle tool, not UI/other controllers.
    with os.fdopen(os.open(root / ".lifecycle.lock", os.O_CREAT | os.O_WRONLY, 0o600), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        api = api_for(root)
        services = json.loads((root / "services.json").read_text())
        manifest = json.loads((root / "lifecycle.json").read_text())
        reviewed = json.loads((root / "account-mappings.json").read_text())
        plan = build_plan(api, services, manifest, reviewed)
        if args.action == "apply":
            apply_plan(api, plan, args.approve_sha256)
            # A partial failure is safe to replan; there is no distributed transaction.
            after = build_plan(api, services, manifest, reviewed)
            if after["operations"]:
                raise RuntimeError("Post-apply drift; replan without resetting credentials")
            print("PASS: IdP lifecycle reconciled; native session revocation remains separate")
        else:
            print(json.dumps(plan, indent=2))
        return 1 if args.action == "check" and plan["operations"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, OSError, KeyError, ValueError, TypeError):
        # Do not emit provider response bodies, token-bearing requests or tracebacks.
        raise SystemExit("Lifecycle failed: API/private input unavailable or invalid") from None
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
