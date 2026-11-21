#!/usr/bin/env python3
"""Pure, fail-closed one-time native bootstrap planner. No credentials or writes.

Snapshot input is private. Output contains only minimal configuration operations;
no client secrets, passwords, OAuth tokens, per-user grants, or group polling.
The profile's ongoing authorization is performed by native OIDC/Rancher RBAC.
"""

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READ = {"get", "list", "watch"}
OWNER = "observer-v1"


def require(value: object, message: str) -> None:
    if not value:
        raise ValueError(message)


def as_list(value: object) -> list[object]:
    """Return a JSON array, stopping on unexpected structure."""
    if not isinstance(value, list):
        error = "Expected a JSON list"
        raise TypeError(error)
    return value


def as_strings(value: object) -> list[str]:
    """Return a JSON array of strings, stopping on unexpected structure."""
    items = as_list(value)
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            error = "Expected a list of JSON strings"
            raise TypeError(error)
        out.append(item)
    return out


def as_dict(value: object) -> dict[str, object]:
    """Return a JSON object, stopping on unexpected structure."""
    if not isinstance(value, dict):
        error = "Expected a JSON object"
        raise TypeError(error)
    return value


def as_str(value: object) -> str:
    """Return a JSON string, stopping on unexpected structure."""
    if not isinstance(value, str):
        error = "Expected a JSON string"
        raise TypeError(error)
    return value


def exact(rows: object, key: str, value: object) -> dict[str, object]:
    records = [as_dict(x) for x in as_list(rows)]
    result = [row for row in records if row.get(key) == value]
    require(len(result) == 1, "Missing/ambiguous reviewed object: " + as_str(value))
    return result[0]


def kpatch(
    obj: Mapping[str, object], path: str, changes: Mapping[str, object]
) -> dict[str, object]:
    meta = as_dict(obj["metadata"])
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": meta["uid"]},
        {"op": "test", "path": "/metadata/resourceVersion", "value": meta["resourceVersion"]},
    ]
    for field, value in changes.items():
        patch.append({"op": "add", "path": "/" + field, "value": value})
    return {"system": "kubernetes", "method": "PATCH", "path": path, "body": patch}


def build(state: object, policy: object) -> object:
    require(
        isinstance(state, dict) and isinstance(policy, dict),
        "Observer state and policy must be objects",
    )
    state_record = state if isinstance(state, dict) else {}
    policy_record = policy if isinstance(policy, dict) else {}
    try:
        return _build(state_record, policy_record)
    except (KeyError, TypeError, AttributeError, IndexError):
        raise ValueError(
            "Malformed observer state/policy: missing field or incorrect nested structure"
        ) from None


def _build(state: Mapping[str, object], policy: Mapping[str, object]) -> list[dict[str, object]]:
    require(policy["version"] == 1 and policy["group"] == "homelab-observer", "Unreviewed profile")
    native_admission = as_list(policy["nativeAdmission"])
    harbor_policy = as_dict(policy["harbor"])
    require(
        set(native_admission) == {"grafana", "wiki", "rancher", "argocd"}
        and len(native_admission) == 4
        and harbor_policy["enabled"] is False,
        "Unreviewed app scope",
    )
    require(
        harbor_policy["projects"] == ["homelab", "library", "spi-triage"],
        "Unreviewed project scope",
    )
    rancher = as_dict(policy["rancher"])
    require(
        rancher["groupPrincipal"] == "genericoidc_group://homelab-observer"
        and rancher["cluster"] == "local"
        and rancher["globalRole"] == "homelab-observer-login"
        and rancher["clusterRole"] == "homelab-observer-cluster",
        "Unreviewed principal/cluster",
    )
    require(
        rancher["humanSessionMinutes"] == 60
        and rancher["denyExtCredentialMinting"] is True
        and rancher["legacySelfCredentialsReadOnly"] is True,
        "Unreviewed session/token policy",
    )
    bindings = [as_dict(b) for b in as_list(state["bindings"])]
    group = exact(state["groups"], "name", policy["group"])
    require(
        group.get("is_superuser") is False
        and group.get("roles") == []
        and group.get("parents") == [],
        "Observer must not carry IdP administration or inherited grants",
    )
    supported_targets = {
        as_dict(app)["pk"]
        for app in as_list(state["apps"])
        if as_dict(app)["slug"] in set(native_admission)
    }
    harbor_app = exact(state["apps"], "slug", "harbor")
    gated_targets = {harbor_app["pk"]}
    unexpected = [
        b
        for b in bindings
        if b.get("group") == group["pk"]
        and bool(b.get("enabled"))
        and b.get("target") not in supported_targets | gated_targets
    ]
    require(
        not unexpected,
        "Observer still admits unsupported apps; migrate legacy admission before rollout",
    )
    # Source RBAC must be activated/reviewed before enabling group admission.
    login = as_dict(state["rancherLoginRole"])
    login_meta = as_dict(login["metadata"])
    require(
        login_meta["name"] == rancher["globalRole"]
        and as_dict(login_meta.get("labels", {})).get("homelab.alchemmist.xyz/identity-profile")
        == OWNER,
        "Native login role has not been deployed under reviewed ownership",
    )
    require(login.get("newUserDefault") is True, "Safe new-user default role is not active")
    for rule in [as_dict(r) for r in as_list(login.get("rules", []))]:
        require(
            not set(as_strings(rule.get("resources", [])))
            & {"tokens", "kubeconfigs", "clusters", "*"},
            "Login role can mint credentials or create infrastructure",
        )
    role = as_dict(state["rancherClusterRole"])
    role_meta = as_dict(role["metadata"])
    require(
        role_meta["name"] == rancher["clusterRole"]
        and as_dict(role_meta.get("labels", {})).get("homelab.alchemmist.xyz/identity-profile")
        == OWNER,
        "Native cluster role ownership mismatch",
    )
    require(
        role.get("context") == "cluster"
        and not role.get("roleTemplateNames")
        and not role.get("administrative")
        and not role.get("external"),
        "Unexpected role inheritance",
    )
    for rule in [as_dict(r) for r in as_list(role["rules"])]:
        require(
            set(as_strings(rule.get("verbs", []))) <= READ
            and "*" not in as_list(rule.get("resources", []))
            and "*" not in as_list(rule.get("apiGroups", [])),
            "Cluster role is not a bounded reader",
        )
        require(
            not set(as_strings(rule.get("resources", [])))
            & {
                "secrets",
                "configmaps",
                "pods/log",
                "pods/exec",
                "pods/attach",
                "pods/portforward",
                "nodes/proxy",
                "services/proxy",
                "serviceaccounts/token",
                "tokens",
                "kubeconfigs",
                "clusterroles",
                "clusterrolebindings",
                "roles",
                "rolebindings",
            },
            "Sensitive reader grant",
        )
    binding = as_dict(state["rancherGroupBinding"])
    binding_meta = as_dict(binding["metadata"])
    require(
        binding.get("groupPrincipalName") == rancher["groupPrincipal"]
        and binding.get("roleTemplateName") == rancher["clusterRole"]
        and binding.get("clusterName") == "local"
        and binding_meta.get("namespace") == "local"
        and not any(binding.get(x) for x in ["userName", "userPrincipalName", "groupName"]),
        "Group binding must not be per-user or point at another cluster",
    )
    definitions = json.loads(
        (ROOT / "deploy/platform/rancher/public-entry/files/observer-rbac.json").read_text()
    )
    for actual, desired in zip([login, role, binding], definitions):
        actual_meta = as_dict(actual["metadata"])
        for key, value in desired.items():
            if key == "metadata":
                require(
                    all(
                        (
                            all(
                                as_dict(actual_meta.get("labels", {})).get(a) == b
                                for a, b in v.items()
                            )
                            if k == "labels"
                            else actual_meta.get(k) == v
                        )
                        for k, v in value.items()
                    ),
                    "Native object ownership drift",
                )
            else:
                require(actual.get(key) == value, "Native object specification drift: " + key)
    require(
        not any(
            login.get(k)
            for k in [
                "inheritedClusterRoles",
                "inheritedFleetWorkspacePermissions",
                "inheritedNamespacedRules",
                "namespacedRules",
            ]
        ),
        "Hidden login inheritance",
    )
    require(not role.get("externalRules"), "Unexpected external role rules")
    ops: list[dict[str, object]] = []
    # Default User grants cluster creation; User Base grants long-lived token
    # minting. Neither is a safe fallback for a new strict UI observer.
    for default in [as_dict(g) for g in as_list(state["globalRoles"])]:
        default_meta = as_dict(default["metadata"])
        if bool(default.get("newUserDefault")) and default_meta["name"] != rancher["globalRole"]:
            require(
                default_meta["name"] in {"user", "user-base"},
                "Unknown default grant; review",
            )
            ops.append(
                kpatch(
                    default,
                    "/apis/management.cattle.io/v3/globalroles/" + as_str(default_meta["name"]),
                    {"newUserDefault": False},
                )
            )
    setting = as_dict(state["rancherSessionSetting"])
    require(
        as_dict(setting["metadata"])["name"] == "auth-user-session-ttl-minutes",
        "Unexpected setting",
    )
    if (setting.get("value") or setting.get("default")) != "60":
        ops.append(
            kpatch(
                setting,
                "/apis/management.cattle.io/v3/settings/auth-user-session-ttl-minutes",
                {"value": "60"},
            )
        )
    # Harbor's default can allow every logged-in user to create projects.
    # Restrict creation before enabling observer admission. Existing project
    # push/pull robot memberships and owner OIDC admin group are untouched.
    harbor = harbor_policy
    require(
        harbor["groupType"] == 3
        and harbor["roleId"] == 3
        and harbor["projectCreationRestriction"] == "adminonly",
        "Not a reviewed Harbor Guest policy",
    )
    state_harbor = as_dict(state["harbor"])
    require(
        state_harbor["oidcGroupsClaim"] == "groups"
        and state_harbor["oidcAdminGroup"] == "homelab-owner",
        "Harbor OIDC mapping drift",
    )
    if state_harbor["projectCreationRestriction"] != "adminonly":
        ops.append(
            {
                "system": "harbor",
                "method": "PUT",
                "path": "/api/v2.0/configurations",
                "body": {"project_creation_restriction": "adminonly"},
            }
        )
    native_groups = [as_dict(g) for g in as_list(state_harbor["groups"])]
    require(
        len(native_groups) <= 1
        and all(
            g.get("group_name") == policy["group"] and g.get("group_type") == 3
            for g in native_groups
        ),
        "Ambiguous/non-OIDC Harbor group",
    )
    harbor_projects = as_dict(state_harbor["projects"])
    for project_value in as_list(harbor["projects"]):
        project = as_str(project_value)
        require(project in harbor_projects, "Missing reviewed Harbor project")
        members = [as_dict(m) for m in as_list(harbor_projects[project])]
        existing = [
            m
            for m in members
            if m.get("entity_type") == "g" and m.get("entity_name") == policy["group"]
        ]
        require(len(existing) <= 1, "Duplicate Harbor group membership")
        if existing:
            require(
                existing[0]["role_id"] == 3,
                "Existing group is not Guest; no silent downgrade/adoption",
            )
            require(
                len(native_groups) == 1 and existing[0].get("entity_id") == native_groups[0]["id"],
                "Harbor membership does not reference the reviewed OIDC group",
            )
            member_id = existing[0].get("id")
            require(
                isinstance(member_id, int)
                and member_id > 0
                and type(member_id) is int
                and not isinstance(member_id, bool),
                "Missing owned Harbor member identity",
            )
            ops.append(
                {
                    "system": "harbor",
                    "method": "DELETE",
                    "path": "/api/v2.0/projects/" + project + "/members/" + str(member_id),
                    "body": None,
                }
            )
    auth = as_dict(state["rancherAuth"])
    require(
        auth.get("enabled") is True
        and auth.get("accessMode") == "restricted"
        and auth.get("groupsClaim") == "groups",
        "Rancher authentication is not the reviewed restricted provider",
    )
    allowed = as_list(auth["allowedPrincipalIds"])
    require(len(set(allowed)) == len(allowed), "Ambiguous admission")
    if rancher["groupPrincipal"] not in allowed:
        ops.append(
            kpatch(
                auth,
                "/apis/management.cattle.io/v3/authconfigs/genericoidc",
                {"allowedPrincipalIds": allowed + [rancher["groupPrincipal"]]},
            )
        )
    # Close only this group's Harbor admission; Guest CLI cache is not revocable.
    for gated in [
        b for b in bindings if b.get("target") == harbor_app["pk"] and b.get("group") == group["pk"]
    ]:
        require(
            gated.get("enabled") is True
            and gated.get("negate") is False
            and not gated.get("policy")
            and not gated.get("user")
            and not gated.get("failure_result"),
            "Complex gated Harbor admission; stop for review",
        )
        require(
            isinstance(gated.get("pk"), str) and bool(gated["pk"]),
            "Missing Harbor binding identity",
        )
        ops.append(
            {
                "system": "authentik",
                "method": "DELETE",
                "path": "policies/bindings/" + as_str(gated["pk"]) + "/",
                "body": None,
            }
        )
    # Admission is last. All existing groups/clients/native identities stay put.
    for slug in native_admission:
        app = exact(state["apps"], "slug", slug)
        require(
            app.get("provider") is not None and app["policy_engine_mode"] == "any",
            "Unexpected native app",
        )
        app_bindings = [b for b in bindings if b.get("target") == app["pk"]]
        require(
            all(
                {"enabled", "negate", "policy", "user", "failure_result", "group"} <= set(b)
                and b.get("enabled") is True
                and b.get("negate") is False
                and not b.get("policy")
                and not b.get("user")
                and not b.get("failure_result")
                and bool(b.get("group"))
                for b in app_bindings
            ),
            "Complex app admission; do not broaden it implicitly",
        )
        own = [b for b in app_bindings if b.get("group") == group["pk"]]
        require(len(own) <= 1, "Duplicate observer admission")
        if not own:
            ops.append(
                {
                    "system": "authentik",
                    "method": "POST",
                    "path": "policies/bindings/",
                    "body": {
                        "target": app["pk"],
                        "group": group["pk"],
                        "enabled": True,
                        "negate": False,
                        "failure_result": False,
                        "order": 100,
                        "user": None,
                        "policy": None,
                    },
                }
            )
    return ops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument(
        "--policy", type=Path, default=ROOT / "deploy/identity/observer/profile.json"
    )
    args = parser.parse_args()
    require(
        not args.snapshot.is_symlink()
        and args.snapshot.is_file()
        and args.snapshot.stat().st_mode & 0o077 == 0,
        "Snapshot must be a private regular file",
    )
    state = json.loads(args.snapshot.read_text())
    policy = json.loads(args.policy.read_text())
    operations = build(state, policy)
    digest = hashlib.sha256(
        json.dumps(
            {"snapshot": state, "policy": policy, "operations": operations},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    print(json.dumps({"applied": False, "plan_hash": digest, "operations": operations}, indent=2))


if __name__ == "__main__":
    main()
