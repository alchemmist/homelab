#!/usr/bin/env python3
"""Catalog-driven app groups and bounded OIDC admission; never manages people.

Default plan is GET-only. Unknown/discovered apps get EMPTY, non-admitting groups.
Native authorization is an explicit service contract, never inferred from a pod.
"""

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import urllib.error
import urllib.request

from typing import cast

from app_iam import GROUP_MARKER, rows, validate_group

BASE = "https://auth.socrat.alchemmist.xyz/api/v3/"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
COLLECTIONS = (
    "core/groups/",
    "core/applications/",
    "providers/oauth2/",
    "propertymappings/provider/scope/",
    "policies/bindings/",
)


def require(ok: object, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def unique(items, key):
    found = {}
    for item in items:
        require(item[key] not in found, "Ambiguous " + key)
        found[item[key]] = item
    return found


def group_expression(aliases):
    require(isinstance(aliases, dict), "Invalid claim aliases")
    for name, values in aliases.items():
        require(
            SLUG.fullmatch(name)
            and isinstance(values, list)
            and all(isinstance(v, str) and SLUG.fullmatch(v) for v in values),
            "Invalid group alias",
        )
        require(
            not any(
                v in ("homelab-owner", "authentik-admins", "homelab-platform-operator")
                or v.startswith("netbird-")
                for v in values
            ),
            "Privileged claim alias refused",
        )
    return (
        "names = [group.name for group in request.user.ak_groups.all()]\n"
        "aliases = " + repr(aliases) + "\n"
        "names = sorted(set(names + [alias for name in names for alias in aliases.get(name, [])]))\n"
    )


def profile_expression(base_expression, aliases):
    # Only transform the reviewed upstream profile groups entry. Preserve all
    # identity/avatar behavior and never mutate the global/default scope mapping.
    old = '"groups": [group.name for group in request.user.groups.all()],'
    require(base_expression.count(old) == 1, "Unreviewed base profile mapping")
    return group_expression(aliases) + base_expression.replace(old, '"groups": names,')


def contracts(services, applications):
    result = {}
    for slug in sorted(set(services) | set(applications)):
        require(SLUG.fullmatch(slug), "Unsafe application slug")
        service = services.get(slug, {})
        roles = service.get("appRoles") or {
            "user": {"assignable": False, "nativeRole": "unreviewed"}
        }
        require(isinstance(roles, dict) and roles, "Missing roles")
        ready = service.get("accessManagement", {}).get("state") == "ready"
        for role, settings in roles.items():
            require(
                SLUG.fullmatch(role) and type(settings.get("assignable")) is bool,
                "Invalid role contract",
            )
            result["app-" + slug + "-" + role] = {
                "slug": slug,
                "role": role,
                "enabled": ready and settings["assignable"],
                "reason": service.get("accessManagement", {}).get(
                    "reason", "No reviewed native adapter"
                ),
            }
    return result


def inventory(api):
    return {
        p: sorted(
            rows(api, p + ("?superuser_full_list=true" if p == "core/applications/" else "")),
            key=lambda v: str(v["pk"]),
        )
        for p in COLLECTIONS
    }


def _existing_admission_pks(
    bindings: list[dict[str, object]], admissible: set[object], slug: str
) -> set[object]:
    """Verify each existing application binding and return the wired group PK set."""
    seen = set()
    for b in bindings:
        require(
            b.get("enabled") is True
            and b.get("negate") is False
            and b.get("failure_result") is False
            and b.get("policy") is None
            and not b.get("expires"),
            "Complex/disabled/expiring policy needs review: " + slug,
        )
        if b.get("group"):
            require(b["group"] in admissible, "Unexpected admission group: " + slug)
            require(b["group"] not in seen, "Duplicate admission group")
            seen.add(b["group"])
        else:
            # Existing exact human bindings are preserved, never broadened,
            # adopted, deleted or created by this generic reconciler.
            require(b.get("user") is not None, "Empty admission binding")
    return seen


def _plan_scope_migration(
    aliases: object,
    mappings: object,
    provider: dict[str, object],
    slug: str,
    operations: list[dict[str, object]],
) -> None:
    """Plan the reviewed per-app profile/groups scope migration for one service."""
    known = cast("dict[str, dict[str, object]]", mappings)
    default = known.get("authentik default OAuth Mapping: OpenID 'profile'")
    require(
        default is not None and default["scope_name"] == "profile",
        "Default profile missing",
    )
    safe_default = cast("dict[str, object]", default)
    prefix = "homelab-app-" + slug + "-"

    wanted = [
        {
            "name": prefix + "profile",
            "scope_name": "profile",
            "expression": profile_expression(safe_default["expression"], aliases),
        },
        {
            "name": prefix + "groups",
            "scope_name": "groups",
            "expression": group_expression(aliases) + 'return {"groups": names}',
        },
    ]
    for want in wanted:
        have = known.get(cast("str", want["name"]))
        if have:
            require(have.get("scope_name") == want["scope_name"], "Scope ownership mismatch")
            require(
                cast("str", have.get("expression", "")).rstrip("\n")
                == cast("str", want["expression"]).rstrip("\n"),
                "Managed scope drift; explicit migration required",
            )
        else:
            operations.append({"kind": "mapping", "settings": want})
    pks = cast("list[object]", provider["property_mappings"])
    by_pk = {m["pk"]: m for m in known.values()}
    require(all(pk in by_pk for pk in pks), "Unknown provider scope")
    retained = [pk for pk in pks if by_pk[pk]["scope_name"] not in ("profile", "groups")]
    # Preserve ONLY the reviewed default scopes on first migration.
    for pk in pks:
        m = by_pk[pk]
        if m["scope_name"] in ("profile", "groups"):
            require(
                m["name"]
                in (
                    safe_default["name"],
                    "homelab-groups",
                    prefix + "profile",
                    prefix + "groups",
                ),
                "Unreviewed custom profile/groups mapping",
            )
    wanted_pks = [known[cast("str", w["name"])]["pk"] for w in wanted if w["name"] in known]
    if len(wanted_pks) != 2 or set(pks) != set(retained + wanted_pks):
        operations.append(
            {
                "kind": "provider",
                "slug": slug,
                "retained": retained,
                "mappingNames": [w["name"] for w in wanted],
            }
        )


def build_plan(state, services):
    groups = unique(state["core/groups/"], "name")
    apps = unique(state["core/applications/"], "slug")
    providers = unique(state["providers/oauth2/"], "pk")
    mappings = unique(state["propertymappings/provider/scope/"], "name")
    declared = contracts(services, apps)
    operations = []
    for name in declared:
        if name in groups:
            validate_group(groups[name])
            require(groups[name].get("children") == [], "App group has inherited children")
        else:
            operations.append({"kind": "group", "name": name})
    # Validate ALL contracts before any write, including existing ANY bindings.
    for slug, service in services.items():
        active = [n for n, c in declared.items() if c["slug"] == slug and c["enabled"]]
        if not active:
            continue
        app = apps.get(slug)
        require(
            app is not None
            and app.get("provider") in providers
            and app.get("policy_engine_mode") == "any",
            "Ready app/provider missing or mode drift: " + slug,
        )
        provider = providers[app["provider"]]
        require(provider["name"] == "homelab-" + slug, "Provider ownership mismatch: " + slug)
        expected_group_names = set(service.get("groups", [])) | set(active)
        bindings = [b for b in state["policies/bindings/"] if b["target"] == app["pk"]]
        admissible = {groups[n]["pk"] for n in expected_group_names if n in groups}
        seen = _existing_admission_pks(bindings, admissible, slug)
        for name in active:
            if name not in groups or groups[name]["pk"] not in seen:
                operations.append({"kind": "binding", "slug": slug, "group": name})
        aliases = service.get("accessManagement", {}).get("claimAliases")
        if aliases:
            _plan_scope_migration(
                aliases, mappings, provider, slug, operations
            )  # Native claims must exist BEFORE group bindings open admission.
    order = {"group": 0, "mapping": 1, "provider": 2, "binding": 3}
    operations.sort(key=lambda op: order[op["kind"]])
    payload = {"services": services, "state": state, "operations": operations}
    return {"sha256": digest(payload), "operations": operations, "groups": declared}


def execute(api, state, services, expected, receipt):
    fresh = inventory(api)
    plan = build_plan(fresh, services)
    require(plan["sha256"] == expected and fresh == state, "Inventory/approval drift; no retry")
    receipt("preimage.json", {"state": state, "services": services, "plan": plan})
    current = copy.deepcopy(state)
    events = []
    for op in plan["operations"]:
        receipt("intent.json", op)
        groups = unique(current["core/groups/"], "name")
        apps = unique(current["core/applications/"], "slug")
        mappings = unique(current["propertymappings/provider/scope/"], "name")
        if op["kind"] == "group":
            require(
                not any(g["name"] == op["name"] for g in rows(api, "core/groups/")),
                "Group create race",
            )
            made = api(
                "POST",
                "core/groups/",
                {
                    "name": op["name"],
                    "is_superuser": False,
                    "parents": [],
                    "children": [],
                    "users": [],
                    "roles": [],
                    "attributes": GROUP_MARKER,
                },
            )
            validate_group(made)
            require(made.get("users") == [] and made.get("children") == [], "Unsafe created group")
            current["core/groups/"].append(made)
        elif op["kind"] == "mapping":
            require(
                not any(
                    m["name"] == op["settings"]["name"]
                    for m in rows(api, "propertymappings/provider/scope/")
                ),
                "Scope create race",
            )
            made = api("POST", "propertymappings/provider/scope/", op["settings"])
            require(
                all(
                    made.get(k, "").rstrip("\n") == v.rstrip("\n")
                    for k, v in op["settings"].items()
                ),
                "Scope verification failed",
            )
            current["propertymappings/provider/scope/"].append(made)
        elif op["kind"] == "provider":
            providers = unique(current["providers/oauth2/"], "pk")
            pk = apps[op["slug"]]["provider"]
            before = providers[pk]
            require(api("GET", "providers/oauth2/" + str(pk) + "/") == before, "Provider CAS drift")
            ids = op["retained"] + [mappings[n]["pk"] for n in op["mappingNames"]]
            response = api("PATCH", "providers/oauth2/" + str(pk) + "/", {"property_mappings": ids})
            receipt("provider-response.json", response)
            made = api("GET", "providers/oauth2/" + str(pk) + "/")
            require(set(made["property_mappings"]) == set(ids), "Provider verification failed")
            require(
                {k: v for k, v in made.items() if k != "property_mappings"}
                == {k: v for k, v in before.items() if k != "property_mappings"},
                "Non-scope provider drift",
            )
            current["providers/oauth2/"] = [
                made if p["pk"] == pk else p for p in current["providers/oauth2/"]
            ]
        else:
            target = apps[op["slug"]]["pk"]
            group = groups[op["group"]]["pk"]
            before = [b for b in state["policies/bindings/"] if b["target"] == target]
            now = rows(api, "policies/bindings/?target=" + target)
            # Account for the bindings we have already created for this app.
            expected_bindings = [b for b in current["policies/bindings/"] if b["target"] == target]
            require(
                sorted(now, key=lambda b: b["pk"])
                == sorted(expected_bindings, key=lambda b: b["pk"]),
                "Binding CAS drift",
            )
            made = api(
                "POST",
                "policies/bindings/",
                {
                    "target": target,
                    "group": group,
                    "order": 100,
                    "enabled": True,
                    "negate": False,
                    "failure_result": False,
                },
            )
            require(
                made.get("group") == group
                and made.get("user") is None
                and made.get("policy") is None,
                "Binding verification failed",
            )
            current["policies/bindings/"].append(made)
        events.append({"operation": op, "object": made})
        receipt("events.json", events)
    after = inventory(api)
    require(build_plan(after, services)["operations"] == [], "Reconciliation not idempotent")
    # Existing group membership, apps and every original binding are protected.
    for path in ("core/groups/", "core/applications/", "policies/bindings/"):
        after_by = unique(after[path], "pk")

        def owned_fields(value):
            # ApplicationSerializer embeds a read-only provider_obj which changes
            # when we update that provider's scopes; it is not an app write.
            if path == "core/applications/" and value is not None:
                return {k: v for k, v in value.items() if k != "provider_obj"}
            return value

        require(
            all(owned_fields(after_by.get(old["pk"])) == owned_fields(old) for old in state[path]),
            "Protected object drift: " + path,
        )
    receipt(
        "verified.json", {"operations": len(events), "idempotent": True, "plan_sha256": expected}
    )
    return len(events)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp:
            fp.close()
        raise RuntimeError("API redirect refused")


def api_for(root):
    credential = root / "credentials.json"
    for path in (root, credential):
        require(
            not path.is_symlink()
            and path.stat().st_uid == os.getuid()
            and not path.stat().st_mode & 0o077,
            "Private owned credential path required",
        )
    token = json.loads(credential.read_text())["AUTHENTIK_BOOTSTRAP_TOKEN"]
    http = urllib.request.build_opener(NoRedirect())

    def api(method, path, data=None):
        base = path.split("?")[0]
        allowed = method == "GET" and (
            base in COLLECTIONS or bool(re.fullmatch(r"providers/oauth2/\d+/", base))
        )
        allowed |= method == "POST" and base in (
            "core/groups/",
            "policies/bindings/",
            "propertymappings/provider/scope/",
        )
        allowed |= (
            method == "PATCH"
            and bool(re.fullmatch(r"providers/oauth2/\d+/", base))
            and set(data or {}) == {"property_mappings"}
        )
        require(allowed, "Request outside app-access boundary")
        req = urllib.request.Request(
            BASE + path,
            method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            data=json.dumps(data).encode() if data is not None else None,
        )
        try:
            with http.open(req, timeout=40) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            status = e.code
            e.close()
            raise RuntimeError(
                "API HTTP " + str(status) + "; stop and inspect receipt, no retry"
            ) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise RuntimeError(
                "API outcome uncertain; stop and inspect receipt, no retry"
            ) from None

    return api


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm-sha256")
    p.add_argument("--public-edge", default="109.173.40.247")
    args = p.parse_args()
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda h, *a, **kw: original(
        args.public_edge if h == "auth.socrat.alchemmist.xyz" else h, *a, **kw
    )
    api = api_for(args.root)
    with open(args.root / "app-access.lock", "a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        services = json.loads((args.root / "services.json").read_text())
        state = inventory(api)
        plan = build_plan(state, services)
        print(
            json.dumps(
                {
                    "sha256": plan["sha256"],
                    "operations": plan["operations"],
                    "groups": plan["groups"],
                },
                indent=2,
            )
        )
        if not args.apply:
            return
        require(args.confirm_sha256 == plan["sha256"], "Explicit fresh plan hash required")
        os.umask(0o077)
        directory = Path(tempfile.mkdtemp(prefix="app-access-", dir=args.root))
        directory.chmod(0o700)

        def receipt(name, value):
            path = directory / name
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(value, indent=2))
            tmp.chmod(0o600)
            os.replace(tmp, path)
            require(json.loads(path.read_text()) == value, "Receipt verification failed")

        print("PRIVATE_RECEIPT", directory, flush=True)
        count = execute(api, state, services, plan["sha256"], receipt)
        print(
            "VERIFIED operations="
            + str(count)
            + "; people/legacy grants unchanged; repeat plan empty"
        )


if __name__ == "__main__":
    main()
