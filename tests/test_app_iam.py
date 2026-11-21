"""Проверки IAM: допуск в приложение не равен его внутренним полномочиям."""

import contextlib
import copy
import io
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict, cast
from unittest.mock import patch
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "ansible/roles/authentik/files"
sys.path.insert(0, str(FILES))
import app_iam
import lifecycle

from tests import test_identity as identity


class LifecycleAPI:
    """Minimal fake lifecycle API that records every write it receives."""
    def __init__(self, fake) -> None:
        self.fake = fake
        self.writes: list[tuple[str, str, object]] = []

    def __call__(self, method, path, data=None) -> object:
        """Serve a fake lifecycle API request through the fake Authentik."""

        if method != "GET":
            self.writes.append((method, path, data))
        if path.endswith(("/add_user/", "/remove_user/")):
            group_pk = path.split("/")[2]
            user = next(u for u in self.fake.data["core/users/"] if u["pk"] == data["pk"])
            group = next(g for g in self.fake.data["core/groups/"] if g["pk"] == group_pk)
            if path.endswith("/add_user/"):
                user["groups"].append(group_pk)
                group["users"].append(user["pk"])
            else:
                user["groups"].remove(group_pk)
                group["users"].remove(user["pk"])
            return None
        req = Request(
            "https://example.invalid/api/v3/" + path,
            method=method,
            data=json.dumps(data).encode() if data is not None else None,
        )
        with self.fake(req) as response:
            return json.load(response)


class LifecyclePlan(TypedDict):
    """Result of lifecycle.build_plan as exercised by these tests."""

    operations: list[dict[str, object]]
    sha256: str


class AppIAMTests(unittest.TestCase):
    """Cover the application IAM provisioning lifecycle end to end."""
    def setUp(self) -> None:
        """Spin up a configured fake Authentik with the reviewed identity map."""

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        helper = identity.IdentityTests()
        helper.setup_root(root)
        self.reviewed = json.loads((ROOT / "deploy/identity/account-mappings.json").read_text())
        self.fake = identity.FakeAuthentik()
        helper.setup_reviewed(root, self.fake)
        # This fixture includes the separately activated LiteLLM scope; the full
        # foundation intentionally refuses to invent its reviewed identity map.
        self.fake.data["propertymappings/provider/scope/"].append(
            {
                "pk": "litellm-identity",
                "name": "homelab-litellm-reviewed-identity",
                "scope_name": "litellm_identity",
            }
        )
        helper.configure(root, self.fake)
        self.api = LifecycleAPI(self.fake)
        self.services = json.loads((root / "services.json").read_text())
        self.manifest = json.loads((ROOT / "deploy/identity/lifecycle.json").read_text())

    def plan(self) -> LifecyclePlan:
        """Build the lifecycle plan against the configured fake API."""

        return cast(
            "LifecyclePlan",
            lifecycle.build_plan(self.api, self.services, self.manifest, self.reviewed),
        )

    def test_legacy_catalog_groups_are_known_without_human_grants(self) -> None:
        """Catalog groups exist without direct human grants or unneeded ops."""

        declared = set(app_iam.LEGACY_GROUPS) | set(app_iam.app_groups(self.services))
        for slug, service in self.services.items():
            assert set(app_iam.admission_groups(slug, service)) <= declared
        teacher = next(g for g in self.fake.data["core/groups/"] if g["name"] == "lms-teachers")
        assert not teacher["is_superuser"]
        assert not teacher.get("users", [])
        assert self.plan()["operations"] == []

    def test_default_manifest_has_no_grants_and_no_writes(self) -> None:
        """The default manifest yields no operations or writes."""

        assert self.plan()["operations"] == []
        assert self.api.writes == []
        for group in self.fake.data["core/groups/"]:
            if group["name"].startswith("app-"):
                assert not group["is_superuser"]
                assert group["users"] == []

    def test_scoped_grant_remove_and_disabled_are_idempotent(self) -> None:
        """Grants, removals and disabling all converge idempotently."""

        tim = next(u for u in self.fake.data["core/users/"] if u["username"] == "antropophag")
        before = list(tim["groups"])
        self.manifest["users"]["antropophag"]["appGroups"] = [
            "app-grafana-viewer",
            "app-wiki-reader",
        ]
        plan = self.plan()
        assert [o["action"] for o in plan["operations"]] == ["add", "add"]
        lifecycle.apply_plan(self.api, plan, plan["sha256"])
        assert self.plan()["operations"] == []
        self.manifest["users"]["antropophag"].update(state="disabled", appGroups=[])
        plan = self.plan()
        assert [o["action"] for o in plan["operations"]] == ["disable", "remove", "remove"]
        lifecycle.apply_plan(self.api, plan, plan["sha256"])
        assert not tim["is_active"]
        assert tim["groups"] == before
        assert self.plan()["operations"] == []
        # Legacy bootstrap never re-enables a disabled initialized account.
        identity.IdentityTests().configure(Path(self.temp.name), self.fake)
        assert not tim["is_active"]

    def test_approval_hash_and_live_state_drift(self) -> None:
        """Stale approval hashes and drifted live state block writes."""

        plan = self.plan()
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            lifecycle.apply_plan(self.api, plan, "stale")
        tim = next(u for u in self.fake.data["core/users/"] if u["username"] == "antropophag")
        tim["is_active"] = False
        assert plan["sha256"] != self.plan()["sha256"]
        assert self.api.writes == []

    def test_uuid_collision_and_email_do_not_link(self) -> None:
        """UUID collisions or email matches never link accounts."""

        self.fake.data["core/users/"][1]["uuid"] = "e51e6956-16b5-455a-bbda-b73f96e85232"
        with self.assertRaisesRegex(RuntimeError, "UUID required"):
            self.plan()
        before = len(self.fake.requests)
        with self.assertRaisesRegex(RuntimeError, "UUID mismatch"):
            identity.IdentityTests().configure(Path(self.temp.name), self.fake)
        assert not any(m != "GET" for m, _, _, _ in self.fake.requests[before:])

    def test_protected_owner_and_elevated_grants_refused(self) -> None:
        """Owner disablement and elevated grants are refused before writes."""

        self.manifest["users"]["alchemmist"]["state"] = "disabled"
        with self.assertRaisesRegex(RuntimeError, "Owner"):
            self.plan()
        self.manifest["users"]["alchemmist"]["state"] = "preserve"
        self.manifest["users"]["antropophag"]["appGroups"] = ["homelab-owner"]
        with self.assertRaisesRegex(RuntimeError, "declared app groups"):
            self.plan()
        assert self.api.writes == []

    def test_unsupported_native_role_and_machine_account_refused(self) -> None:
        """Unready native roles and machine accounts are refused."""

        self.manifest["users"]["antropophag"]["appGroups"] = ["app-rancher-user"]
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            self.plan()
        self.manifest["users"]["antropophag"]["appGroups"] = []
        self.fake.data["core/users/"][1]["type"] = "service_account"
        with self.assertRaisesRegex(RuntimeError, "service/external"):
            self.plan()

    def test_app_group_inheritance_or_superuser_refused(self) -> None:
        """Tainted app groups with inheritance or superuser are refused."""

        group = next(g for g in self.fake.data["core/groups/"] if g["name"] == "app-grafana-viewer")
        owner = next(g for g in self.fake.data["core/groups/"] if g["name"] == "homelab-owner")
        rbac = {
            "pk": "rbac-ancestor",
            "name": "rbac-ancestor",
            "is_superuser": False,
            "parents": [],
            "roles": ["admin-role"],
            "attributes": {},
            "users": [],
        }
        self.fake.data["core/groups/"].append(rbac)
        self.manifest["users"]["antropophag"]["appGroups"] = ["app-grafana-viewer"]
        for field, value in [
            ("parents", [owner["pk"]]),
            ("parents", [rbac["pk"]]),
            ("is_superuser", True),
            ("roles", ["admin-role"]),
        ]:
            old = copy.deepcopy(group)
            group[field] = value
            with self.assertRaisesRegex(RuntimeError, "non-superuser"):
                self.plan()
            assert self.api.writes == []
            group.clear()
            group.update(old)

    def test_incomplete_current_group_schema_refused_before_assignment(self) -> None:
        """Incomplete group schemas are refused before any assignment."""

        group = next(g for g in self.fake.data["core/groups/"] if g["name"] == "app-grafana-viewer")
        self.manifest["users"]["antropophag"]["appGroups"] = ["app-grafana-viewer"]
        for field in ["parents", "roles", "is_superuser"]:
            for value in ["missing", None, {}, "", 0]:
                old = copy.deepcopy(group)
                if value == "missing":
                    group.pop(field)
                else:
                    group[field] = value
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaisesRegex(RuntimeError, "non-superuser"),
                ):
                    self.plan()
                assert self.api.writes == []
                group.clear()
                group.update(old)

    def test_binding_drift_is_not_silently_reset(self) -> None:
        """Policy binding drift aborts instead of being silently reset."""

        binding = self.fake.data["policies/bindings/"][0]
        for change in [
            {"enabled": False},
            {"negate": True},
            {"group": "unknown-group"},
            {"user": 6},
        ]:
            old = copy.deepcopy(binding)
            binding.update(change)
            with self.assertRaisesRegex(RuntimeError, "binding drift"):
                self.plan()
            with self.assertRaisesRegex(RuntimeError, "binding drift"):
                identity.IdentityTests().configure(Path(self.temp.name), self.fake)
            assert binding == {**old, **change}
            binding.clear()
            binding.update(old)

    def test_missing_user_is_not_created_and_omission_is_not_revocation(self) -> None:
        """Missing users abort; manifest omission does not revoke access."""

        self.fake.data["core/users/"].pop()
        with self.assertRaisesRegex(RuntimeError, "existing username"):
            self.plan()
        before = len(self.fake.requests)
        with self.assertRaisesRegex(RuntimeError, "instead of recreating"):
            identity.IdentityTests().configure(Path(self.temp.name), self.fake)
        assert not any(m != "GET" for m, _, _, _ in self.fake.requests[before:])
        del self.manifest["users"]["antropophag"]
        assert self.plan()["operations"] == []
        assert self.api.writes == []

    def test_foreign_app_group_is_not_adopted(self) -> None:
        """Unmarked app groups are never adopted by the reconciler."""

        group = next(g for g in self.fake.data["core/groups/"] if g["name"] == "app-grafana-viewer")
        group["attributes"] = {}
        with self.assertRaisesRegex(RuntimeError, "unmarked app group"):
            self.plan()
        with self.assertRaisesRegex(RuntimeError, "unmarked app group"):
            identity.IdentityTests().configure(Path(self.temp.name), self.fake)

    def test_policy_mode_is_not_silently_reset(self) -> None:
        """Application policy engine mode drift aborts both planners."""

        self.fake.data["core/applications/"][0]["policy_engine_mode"] = "all"
        with self.assertRaisesRegex(RuntimeError, "mode drift"):
            self.plan()
        with self.assertRaisesRegex(RuntimeError, "mode drift"):
            identity.IdentityTests().configure(Path(self.temp.name), self.fake)

    def test_pagination_and_binding_duplicates(self) -> None:
        """Pagination follows cursors; duplicate bindings raise drift errors."""

        calls = []


        def api(_method, path) -> dict[str, object]:
            calls.append(path)
            page = len(calls)
            return {"results": [page], "pagination": {"next": page == 1}}

        assert app_iam.rows(api, "core/groups/") == [1, 2]
        assert "page=2" in calls[-1]
        with self.assertRaisesRegex(RuntimeError, "binding drift"):
            app_iam.validate_bindings([{"group": "a"}, {"group": "a"}], {"a"})

    def test_wiki_integration_keeps_exact_links_and_overrides(self) -> None:
        """Wiki integration emits exact reviewed links and refuses mismatches."""

        writes = []

        def run(args, **kwargs) -> subprocess.CompletedProcess[str]:
            if "apply" in args:
                writes.append(json.loads(kwargs["input"]))
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            patch("sys.argv", ["integrate.py", self.temp.name, "wiki"]),
            patch("urllib.request.urlopen", self.fake),
            patch("subprocess.run", run),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runpy.run_path(
                str(ROOT / "ansible/roles/identity_integrations/files/integrate.py"),
                run_name="__main__",
            )
        assert len(writes) == 1
        data = writes[0]["stringData"]
        assert json.loads(data["WIKI_OIDC_LINKS"]) == {a["idpUserUuid"]: a["wikiUserId"] for a in self.reviewed.values()}
        assert json.loads(data["WIKI_OIDC_SUBJECT_ROLES"]) == {a["idpUserUuid"]: a["wikiRole"] for a in self.reviewed.values()}
        assert json.loads(data["WIKI_OIDC_GROUP_ROLES"])["app-wiki-editor"] == "editor"
        # A same-name/email replacement must not rewrite any native link.
        self.fake.data["core/users/"][1]["uuid"] = "e51e6956-16b5-455a-bbda-b73f96e85232"
        with (
            patch("sys.argv", ["integrate.py", self.temp.name, "wiki"]),
            patch("urllib.request.urlopen", self.fake),
            patch("subprocess.run") as kube,
            self.assertRaisesRegex(RuntimeError, "subject mismatch"),
        ):
            runpy.run_path(
                str(ROOT / "ansible/roles/identity_integrations/files/integrate.py"),
                run_name="__main__",
            )
        kube.assert_not_called()

    def test_native_role_boundaries_and_subject_overrides_preserved(self) -> None:
        """Native role boundaries and reviewed subject overrides are preserved."""

        import yaml

        env = yaml.safe_load((ROOT / "deploy/identity/grafana-oidc-values.yaml").read_text())[
            "grafana"
        ]["env"]
        expression = env["GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH"]
        assert expression.startswith("contains(groups[*], 'homelab-owner') && 'GrafanaAdmin'")
        assert "'app-grafana-editor') && 'Editor'" in expression
        webui = json.loads((ROOT / "deploy/identity/open-webui-env.json").read_text())
        assert webui["OAUTH_ADMIN_ROLES"] == "homelab-owner"
        assert webui["ENABLE_OAUTH_EMAIL_FALLBACK"] == "True"
        assert webui["OAUTH_MERGE_ACCOUNTS_BY_EMAIL"] == "False"
        assert "app-open-webui-user" in webui["OAUTH_ALLOWED_ROLES"]
        assert self.reviewed["antropophag"]["wikiRole"] == "editor"
        assert self.reviewed["alchemmist"]["idpUserUuid"] == self.manifest["users"]["alchemmist"]["uuid"]
        for provider in self.fake.data["providers/oauth2/"]:
            assert provider["authorization_flow"] == "default-provider-authorization-explicit-consent"
            assert provider["authentication_flow"] == "default-authentication-flow"
            assert provider["sub_mode"] == self.services[provider["name"][8:]].get("subMode", "hashed_user_id")
        scope = next(
            s
            for s in self.fake.data["propertymappings/provider/scope/"]
            if s.get("name") == "homelab-groups"
        )
        assert scope["expression"] == 'return {"groups": [group.name for group in request.user.ak_groups.all()]}'


if __name__ == "__main__":
    unittest.main()
