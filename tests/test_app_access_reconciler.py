"""Pure app access reconciler checks; no credentials or live calls."""

import copy
import io
import json
import tempfile
from unittest.mock import patch
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import NotRequired, TypedDict, cast
import unittest

FILES = Path(__file__).resolve().parents[1] / "ansible/roles/authentik/files"
sys.path.insert(0, str(FILES))
import reconcile_app_access as access


class CatalogApp(TypedDict):
    """One application's catalog entry: groups, roles, and access state."""

    groups: list[str]
    appRoles: dict[str, dict[str, object]]
    accessManagement: NotRequired[dict[str, object]]


def fixture() -> tuple[
    dict[str, list[dict[str, object]]],
    dict[str, CatalogApp],
]:
    owner = {"pk": "owner", "name": "homelab-owner"}
    profile = {
        "pk": "profile",
        "name": "authentik default OAuth Mapping: OpenID 'profile'",
        "scope_name": "profile",
        "expression": 'return {"groups": [group.name for group in request.user.groups.all()], "name": request.user.name}',
    }
    state = {
        "core/groups/": [owner],
        "core/applications/": [
            {"pk": "app", "slug": "example", "provider": 1, "policy_engine_mode": "any"}
        ],
        "providers/oauth2/": [
            {"pk": 1, "name": "homelab-example", "property_mappings": ["profile"]}
        ],
        "propertymappings/provider/scope/": [profile],
        "policies/bindings/": [
            {
                "pk": "binding",
                "target": "app",
                "group": "owner",
                "user": None,
                "policy": None,
                "enabled": True,
                "negate": False,
                "failure_result": False,
                "expires": None,
            }
        ],
    }
    catalog = {
        "example": {
            "groups": ["homelab-owner"],
            "appRoles": {"user": {"assignable": True, "nativeRole": "user"}},
            "accessManagement": {"state": "ready"},
        }
    }
    return cast("dict[str, list[dict[str, object]]]", state), cast("dict[str, CatalogApp]", catalog)


class FakeAPI:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.writes = []

    def __call__(self, method, path, payload=None):
        base = path.split("?")[0]
        if method == "GET":
            if base.startswith("providers/oauth2/") and base != "providers/oauth2/":
                return copy.deepcopy(
                    next(
                        p
                        for p in self.state["providers/oauth2/"]
                        if str(p["pk"]) == base.split("/")[2]
                    )
                )
            rows = copy.deepcopy(self.state[base])
            if "?target=" in path:
                target = path.split("?target=")[1].split("&")[0]
                rows = [r for r in rows if r["target"] == target]
            return {"results": rows, "pagination": {"next": None}}
        self.writes.append((method, path, payload))
        if method == "POST":
            made = dict(payload, pk="created-" + str(len(self.writes)))
            if base == "policies/bindings/":
                made.update(user=None, policy=None, expires=None)
            self.state[base].append(made)
            return copy.deepcopy(made)
        pk = int(base.split("/")[2])
        item = next(p for p in self.state["providers/oauth2/"] if p["pk"] == pk)
        item.update(payload)
        for app in self.state["core/applications/"]:
            if app["provider"] == pk:
                app["provider_obj"] = copy.deepcopy(item)
        # PATCH may return a reduced serializer; verify with a fresh detail GET.
        return {"pk": pk, **copy.deepcopy(payload)}


class AppAccessTests(unittest.TestCase):
    def test_api_guard_accepts_provider_get_but_rejects_other_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            credential = root / "credentials.json"
            credential.write_text(json.dumps({"AUTHENTIK_BOOTSTRAP_TOKEN": "fake-test-only"}))
            credential.chmod(0o600)
            fake = SimpleNamespace(open=lambda *a, **kw: io.BytesIO(b'{"pk": 3}'))
            with patch.object(access.urllib.request, "build_opener", return_value=fake):
                api = access.api_for(root)
            self.assertEqual(api("GET", "providers/oauth2/3/"), {"pk": 3})
            with self.assertRaises(RuntimeError):
                api("PATCH", "providers/oauth2/3/", {"client_secret": "not-allowed"})
            with self.assertRaises(RuntimeError):
                api("POST", "core/users/", {})

    def test_default_scope_selection_does_not_cross_app_profiles(self) -> None:
        from app_iam import standard_scope_ids

        scopes = [
            {
                "pk": name,
                "scope_name": name,
                "name": "authentik default OAuth Mapping: OpenID '" + name + "'",
            }
            for name in ("openid", "profile", "email")
        ]
        scopes += [
            {"pk": "other-app", "scope_name": "profile", "name": "homelab-app-other-profile"}
        ]
        self.assertEqual(standard_scope_ids(scopes), ["openid", "profile", "email"])
        with self.assertRaises(RuntimeError):
            standard_scope_ids(scopes + [scopes[0]])

    def test_new_registered_app_generates_group_without_hardcoded_allowlist(self) -> None:
        state, catalog = fixture()
        operations = access.build_plan(state, catalog)["operations"]
        self.assertEqual([x["kind"] for x in operations], ["group", "binding"])
        self.assertEqual(operations[0]["name"], "app-example-user")

    def test_discovered_unknown_app_gets_empty_group_not_admission(self) -> None:
        state, _ = fixture()
        plan = access.build_plan(state, {})
        self.assertEqual(plan["operations"], [{"kind": "group", "name": "app-example-user"}])
        self.assertFalse(plan["groups"]["app-example-user"]["enabled"])

    def test_unready_roles_never_open_access(self) -> None:
        state, catalog = fixture()
        catalog["example"]["accessManagement"]["state"] = "blocked"
        self.assertEqual(
            [op["kind"] for op in access.build_plan(state, catalog)["operations"]], ["group"]
        )

    def test_missing_native_adapter_defaults_closed(self) -> None:
        state, catalog = fixture()
        del catalog["example"]["accessManagement"]
        self.assertFalse(
            any(x["kind"] == "binding" for x in access.build_plan(state, catalog)["operations"])
        )

    def test_managed_group_inheritance_or_foreign_owner_refused(self) -> None:
        state, catalog = fixture()
        group = {
            "pk": "g",
            "name": "app-example-user",
            "is_superuser": False,
            "parents": [],
            "children": [],
            "users": [],
            "roles": [],
            "attributes": access.GROUP_MARKER,
        }
        state["core/groups/"].append(group)
        for field, value in [
            ("parents", ["owner"]),
            ("children", ["other"]),
            ("roles", ["admin"]),
            ("attributes", {}),
        ]:
            changed = copy.deepcopy(state)
            changed["core/groups/"][-1][field] = value
            with self.assertRaises(RuntimeError):
                access.build_plan(changed, catalog)

    def test_policy_bypass_or_unknown_scope_refused_before_any_write(self) -> None:
        state, catalog = fixture()
        for field, value in [
            ("negate", True),
            ("enabled", False),
            ("policy", "restrictive-policy"),
        ]:
            changed = copy.deepcopy(state)
            changed["policies/bindings/"][0][field] = value
            with self.assertRaises(RuntimeError):
                access.build_plan(changed, catalog)

    def test_scoped_alias_preserves_identity_and_not_global_membership(self) -> None:
        state, catalog = fixture()
        expression = access.profile_expression(
            state["propertymappings/provider/scope/"][0]["expression"],
            {"app-example-user": ["legacy-example-user"]},
        )
        groups = [SimpleNamespace(name="app-example-user")]
        namespace = {
            "request": SimpleNamespace(
                user=SimpleNamespace(name="Person", ak_groups=SimpleNamespace(all=lambda: groups))
            )
        }
        exec(
            "def mapping():\n" + "\n".join("    " + line for line in expression.splitlines()),
            namespace,
        )
        self.assertEqual(
            namespace["mapping"]()["groups"], ["app-example-user", "legacy-example-user"]
        )
        self.assertEqual([g.name for g in groups], ["app-example-user"])
        self.assertNotIn("homelab-owner", namespace["mapping"]()["groups"])
        with self.assertRaises(RuntimeError):
            access.group_expression({"app-example-user": ["homelab-owner"]})

    def test_apply_idempotent_and_preserves_people_and_owner(self) -> None:
        state, catalog = fixture()
        api = FakeAPI(state)
        receipts = {}
        state = access.inventory(api)
        plan = access.build_plan(state, catalog)
        count = access.execute(
            api,
            state,
            catalog,
            plan["sha256"],
            lambda name, obj: receipts.update({name: copy.deepcopy(obj)}),
        )
        self.assertEqual(count, 2)
        self.assertEqual(access.build_plan(access.inventory(api), catalog)["operations"], [])
        self.assertEqual(api.state["core/groups/"][0], state["core/groups/"][0])
        self.assertEqual(api.state["policies/bindings/"][0], state["policies/bindings/"][0])
        self.assertTrue(receipts["verified.json"]["idempotent"])

    def test_drift_stops_before_write(self) -> None:
        state, catalog = fixture()
        api = FakeAPI(state)
        plan = access.build_plan(state, catalog)
        api.state["core/applications/"][0]["policy_engine_mode"] = "all"
        with self.assertRaises(RuntimeError):
            access.execute(api, state, catalog, plan["sha256"], lambda *args: None)
        self.assertEqual(api.writes, [])

    def test_alias_scopes_attached_before_admission_and_idempotent(self) -> None:
        state, catalog = fixture()
        catalog["example"]["accessManagement"]["claimAliases"] = {
            "app-example-user": ["legacy-example-user"]
        }
        api = FakeAPI(state)
        state = access.inventory(api)
        plan = access.build_plan(state, catalog)
        self.assertEqual(
            [x["kind"] for x in plan["operations"]],
            ["group", "mapping", "mapping", "provider", "binding"],
        )
        access.execute(api, state, catalog, plan["sha256"], lambda *args: None)
        self.assertEqual(access.build_plan(access.inventory(api), catalog)["operations"], [])


if __name__ == "__main__":
    unittest.main()
