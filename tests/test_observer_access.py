"""Hermetic native authorization-policy and bounded-bootstrap regression tests."""

import ast
import copy
import importlib.util
import json
from collections.abc import Iterable
from pathlib import Path
import unittest
import contextlib
import io
import tempfile
from typing import TypedDict
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "observer_plan", ROOT / "scripts/observer-access-plan.py"
)
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)
POLICY = json.loads((ROOT / "deploy/identity/observer/profile.json").read_text())
RBAC = json.loads(
    (ROOT / "deploy/platform/rancher/public-entry/files/observer-rbac.json").read_text()
)


class HarborState(TypedDict):
    """Harbor portion of the snapshot the observer plan converges."""

    groups: list[dict[str, object]]
    oidcGroupsClaim: str
    oidcAdminGroup: str
    projectCreationRestriction: str
    projects: dict[str, list[dict[str, object]]]


class Snapshot(TypedDict):
    """Synthetic authentik/Rancher/Harbor snapshot shape used by every test."""

    groups: list[dict[str, object]]
    rancherLoginRole: dict[str, object]
    rancherClusterRole: dict[str, object]
    rancherGroupBinding: dict[str, object]
    globalRoles: list[dict[str, object]]
    rancherSessionSetting: dict[str, object]
    rancherAuth: dict[str, object]
    harbor: HarborState
    apps: list[dict[str, object]]
    bindings: list[dict[str, object]]


class ChatState(TypedDict):
    """Authentik application state exercised by the one-time chat migration."""

    users: list[dict[str, object]]
    groups: list[dict[str, object]]
    app: dict[str, object]
    bindings: list[dict[str, object]]


def _metadata_name(obj: dict[str, object]) -> str:
    metadata = obj["metadata"]
    assert isinstance(metadata, dict)
    name = metadata["name"]
    assert isinstance(name, str)
    return name


def _strings(value: object) -> list[str]:
    """Read a JSON array that the contracts already keep all-string."""
    assert isinstance(value, list)
    return [item for item in value if isinstance(item, str)]


def _binding_pk(binding: dict[str, object]) -> str:
    pk = binding.get("pk", "")
    assert isinstance(pk, str)
    return pk


def fixture() -> Snapshot:
    login, role, binding = copy.deepcopy(RBAC)
    for obj in [login, role, binding]:
        obj["metadata"].update(uid="uid-" + obj["metadata"]["name"], resourceVersion="17")
    global_user = {
        "metadata": {"name": "user", "uid": "user-uid", "resourceVersion": "8"},
        "newUserDefault": True,
        "rules": [{"resources": ["clusters"], "verbs": ["create"]}],
    }
    return {
        "groups": [
            {
                "name": "homelab-observer",
                "pk": "group-id",
                "is_superuser": False,
                "roles": [],
                "parents": [],
            }
        ],
        "rancherLoginRole": login,
        "rancherClusterRole": role,
        "rancherGroupBinding": binding,
        "globalRoles": [global_user, login],
        "rancherSessionSetting": {
            "metadata": {
                "name": "auth-user-session-ttl-minutes",
                "uid": "ttl-uid",
                "resourceVersion": "4",
            },
            "value": "",
            "default": "960",
        },
        "rancherAuth": {
            "metadata": {
                "name": "genericoidc",
                "uid": "auth-uid",
                "resourceVersion": "9",
            },
            "enabled": True,
            "accessMode": "restricted",
            "groupsClaim": "groups",
            "clientSecret": "MUST-NOT-APPEAR-IN-PLAN",
            "allowedPrincipalIds": [
                "genericoidc_user://owner-subject",
                "genericoidc_user://preserved-subject",
            ],
        },
        "harbor": {
            "groups": [],
            "oidcGroupsClaim": "groups",
            "oidcAdminGroup": "homelab-owner",
            "projectCreationRestriction": "everyone",
            "projects": {p: [] for p in POLICY["harbor"]["projects"]},
        },
        "apps": [
            {
                "slug": slug,
                "pk": "app-" + slug,
                "provider": i,
                "policy_engine_mode": "any",
            }
            for i, slug in enumerate(POLICY["nativeAdmission"] + ["harbor"], start=1)
        ],
        "bindings": [],
    }


def converge(state: Snapshot, operations: Iterable[dict[str, object]]) -> None:
    for op in operations:
        system = op["system"]
        if system == "kubernetes":
            path = op["path"]
            assert isinstance(path, str)
            name = path.split("/")[-1]
            objects = state["globalRoles"] + [
                state["rancherSessionSetting"],
                state["rancherAuth"],
            ]
            obj = next(o for o in objects if _metadata_name(o) == name)
            changes = op["body"]
            assert isinstance(changes, list)
            for change in changes:
                assert isinstance(change, dict)
                if change["op"] == "add":
                    change_path = change["path"]
                    assert isinstance(change_path, str)
                    obj[change_path[1:]] = copy.deepcopy(change["value"])
        elif system == "harbor" and op["method"] == "PUT":
            body = op["body"]
            assert isinstance(body, dict)
            state["harbor"]["projectCreationRestriction"] = body["project_creation_restriction"]
        elif system == "harbor" and op["method"] == "DELETE":
            path = op["path"]
            assert isinstance(path, str)
            segments = path.split("/")
            project = segments[-3]
            state["harbor"]["projects"][project] = [
                m for m in state["harbor"]["projects"][project] if m["id"] != int(segments[-1])
            ]
        elif system == "authentik" and op["method"] == "DELETE":
            path = op["path"]
            assert isinstance(path, str)
            state["bindings"] = [
                b for b in state["bindings"] if "policies/bindings/" + _binding_pk(b) + "/" != path
            ]
        elif system == "harbor":
            path = op["path"]
            assert isinstance(path, str)
            project = path.split("/")[-2]
            state["harbor"]["groups"] = [
                {"id": 101, "group_name": "homelab-observer", "group_type": 3}
            ]
            state["harbor"]["projects"][project].append(
                {
                    "entity_type": "g",
                    "entity_name": "homelab-observer",
                    "entity_id": 101,
                    "role_id": 3,
                }
            )
        else:
            body = op["body"]
            assert isinstance(body, dict)
            state["bindings"].append(copy.deepcopy(body))


def permits(
    rules: Iterable[dict[str, object]],
    group: str,
    resource: str,
    verb: str,
    name: str | None = None,
) -> bool:
    return any(
        group in _strings(r["apiGroups"])
        and resource in _strings(r["resources"])
        and verb in _strings(r["verbs"])
        and ("resourceNames" not in r or name in _strings(r.get("resourceNames", [])))
        for r in rules
    )


class ObserverPolicyTests(unittest.TestCase):
    """Validate the observer access policy deployment values."""
    def test_reviewed_activation_enables_native_rancher_roles(self) -> None:
        values = (ROOT / "deploy/platform/rancher/public-entry/values.yaml").read_text()
        assert "observerAccess:\n  enabled: true" in values

    def test_native_only_no_user_objects(self) -> None:
        assert [o["kind"] for o in RBAC] == ["GlobalRole", "RoleTemplate", "ClusterRoleTemplateBinding"]
        binding = RBAC[2]
        assert binding["groupPrincipalName"] == "genericoidc_group://homelab-observer"
        assert not any(k in binding for k in ["userName", "userPrincipalName"])

    def test_positive_cluster_read_matrix(self) -> None:
        for group, resource in [
            ("", "pods"),
            ("", "nodes"),
            ("", "namespaces"),
            ("apps", "deployments"),
            ("batch", "jobs"),
            ("networking.k8s.io", "ingresses"),
            ("metrics.k8s.io", "pods"),
            ("monitoring.coreos.com", "prometheusrules"),
        ]:
            for verb in ["get", "list", "watch"]:
                with self.subTest(group=group, resource=resource, verb=verb):
                    assert permits(RBAC[1]["rules"], group, resource, verb)

    def test_no_sensitive_reads(self) -> None:
        for group, resource in [
            ("", "secrets"),
            ("", "configmaps"),
            ("", "pods/log"),
            ("", "nodes/proxy"),
            ("", "services/proxy"),
            ("rbac.authorization.k8s.io", "roles"),
            ("rbac.authorization.k8s.io", "clusterrolebindings"),
        ]:
            for verb in ["get", "list", "watch"]:
                with self.subTest(group=group, resource=resource, verb=verb):
                    assert not permits(RBAC[1]["rules"], group, resource, verb)

    def test_no_infrastructure_mutations_or_escalation(self) -> None:
        rules = RBAC[1]["rules"] + RBAC[0]["rules"]
        for group, resource in [
            ("", "pods"),
            ("", "pods/exec"),
            ("", "pods/attach"),
            ("", "pods/portforward"),
            ("", "secrets"),
            ("", "serviceaccounts/token"),
            ("apps", "deployments"),
            ("management.cattle.io", "projects"),
            ("management.cattle.io", "clusters"),
            ("management.cattle.io", "globalrolebindings"),
            ("management.cattle.io", "roletemplates"),
            ("ext.cattle.io", "tokens"),
            ("ext.cattle.io", "kubeconfigs"),
            ("rbac.authorization.k8s.io", "roles"),
            ("rbac.authorization.k8s.io", "clusterrolebindings"),
        ]:
            for verb in [
                "create",
                "update",
                "patch",
                "delete",
                "deletecollection",
                "bind",
                "escalate",
                "impersonate",
            ]:
                with self.subTest(group=group, resource=resource, verb=verb):
                    assert not permits(rules, group, resource, verb)

    def test_cluster_metadata_is_named_local_only(self) -> None:
        rules = RBAC[1]["rules"]
        assert permits(rules, "management.cattle.io", "clusters", "get", "local")
        assert not permits(rules, "management.cattle.io", "clusters", "get", "other-cluster")
        assert not permits(rules, "management.cattle.io", "clusters", "list")

    def test_bounded_minimal_plan_no_secrets_no_machine_ttl(self) -> None:
        state = fixture()
        before = copy.deepcopy(state)
        operations = plan.build(state, POLICY)
        assert state == before
        text = json.dumps(operations)
        assert "MUST-NOT-APPEAR-IN-PLAN" not in text
        assert "auth-token-max-ttl-minutes" not in text
        assert "core/users/" not in text
        assert "password" not in text
        assert all(o["path"] != "core/groups/group-id/" for o in operations)
        assert sum(o["system"] == "harbor" and o["method"] == "POST" for o in operations) == 0
        assert sum(o["system"] == "authentik" for o in operations) == 4

    def test_harbor_gate_removes_only_exact_owned_guest_and_observer_admission(
        self,
    ) -> None:
        state = fixture()
        state["harbor"]["groups"] = [{"id": 101, "group_name": "homelab-observer", "group_type": 3}]
        for n, project in enumerate(POLICY["harbor"]["projects"], start=1):
            state["harbor"]["projects"][project] = [
                {
                    "id": n,
                    "entity_type": "g",
                    "entity_name": "homelab-observer",
                    "entity_id": 101,
                    "role_id": 3,
                }
            ]
        harbor = next(a for a in state["apps"] if a["slug"] == "harbor")
        state["bindings"] = [
            {
                "pk": "owned-harbor-binding",
                "target": harbor["pk"],
                "group": "group-id",
                "enabled": True,
                "negate": False,
                "policy": None,
                "user": None,
                "failure_result": False,
            }
        ]
        ops = plan.build(state, POLICY)
        assert sum(o["system"] == "harbor" and o["method"] == "DELETE" for o in ops) == 3
        assert sum(o["system"] == "authentik" and o["method"] == "DELETE" for o in ops) == 1
        converge(state, ops)
        assert plan.build(state, POLICY) == []

    def test_cas_and_preserved_principals(self) -> None:
        operations = plan.build(fixture(), POLICY)
        for op in operations:
            if op["system"] == "kubernetes":
                assert [p["path"] for p in op["body"][:2]] == ["/metadata/uid", "/metadata/resourceVersion"]
                assert all(p["op"] == "test" for p in op["body"][:2])
        auth = next(o for o in operations if o["path"].endswith("/authconfigs/genericoidc"))
        principals = fixture()["rancherAuth"]["allowedPrincipalIds"]
        assert isinstance(principals, list)
        assert auth["body"][-1]["value"] == [*principals, "genericoidc_group://homelab-observer"]

    def test_safe_defaults_and_harbor_before_admission(self) -> None:
        operations = plan.build(fixture(), POLICY)
        first_auth = next(i for i, o in enumerate(operations) if o["system"] == "authentik")
        assert all(o["system"] == "authentik" for o in operations[first_auth:])
        assert operations[0]["body"][-1] == {"op": "add", "path": "/newUserDefault", "value": False}
        harbor_ops = [o for o in operations if o["system"] == "harbor"]
        assert harbor_ops[0]["body"] == {"project_creation_restriction": "adminonly"}

    def test_idempotent_native_bootstrap(self) -> None:
        state = fixture()
        converge(state, plan.build(state, POLICY))
        assert plan.build(state, POLICY) == []

    def test_multiple_future_users_do_not_change_plan(self) -> None:
        state = fixture()
        converge(state, plan.build(state, POLICY))
        state["groups"][0]["users"] = [94, 100, 101, 102]
        assert plan.build(state, POLICY) == []

    def test_reject_dangerous_live_drift(self) -> None:
        mutations = [
            lambda s: s["groups"][0].update(is_superuser=True),
            lambda s: s["groups"][0].update(roles=["idp-read-role"]),
            lambda s: s["groups"][0].update(parents=["idp-admin-group"]),
            lambda s: s["rancherLoginRole"].update(newUserDefault=False),
            lambda s: s["rancherLoginRole"].update(inheritedClusterRoles=["admin"]),
            lambda s: s["rancherLoginRole"]["rules"].append(
                {"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"]}
            ),
            lambda s: s["rancherClusterRole"].update(roleTemplateNames=["cluster-member"]),
            lambda s: s["rancherClusterRole"].update(external=True),
            lambda s: s["rancherClusterRole"]["rules"].append(
                {"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"]}
            ),
            lambda s: s["rancherClusterRole"]["rules"][0].update(verbs=["*"]),
            lambda s: s["rancherClusterRole"]["rules"][0].update(resources=["*"]),
            lambda s: s["rancherGroupBinding"].update(userName="a-human"),
            lambda s: s["rancherGroupBinding"].update(
                groupPrincipalName="genericoidc_group://other"
            ),
            lambda s: s["rancherGroupBinding"].update(clusterName="other"),
            lambda s: s["rancherAuth"].update(accessMode="unrestricted"),
            lambda s: s["rancherAuth"].update(groupsClaim="untrusted"),
            lambda s: s["harbor"].update(oidcAdminGroup="homelab-observer"),
            lambda s: s["harbor"]["projects"]["homelab"].append(
                {"entity_type": "g", "entity_name": "homelab-observer", "role_id": 1}
            ),
            lambda s: s["apps"][0].update(policy_engine_mode="all"),
            lambda s: s["bindings"].append(
                {"target": "legacy-open-webui", "enabled": True, "group": "group-id"}
            ),
            lambda s: s["bindings"].append(
                {
                    "target": "app-grafana",
                    "enabled": True,
                    "group": "group-id",
                    "negate": True,
                }
            ),
            lambda s: s["globalRoles"].append(
                {"metadata": {"name": "unknown"}, "newUserDefault": True}
            ),
        ]
        for change in mutations:
            with self.subTest(change=mutations.index(change)):
                state = fixture()
                change(state)
                with self.assertRaises(ValueError):
                    plan.build(state, POLICY)

    def test_reject_policy_scope_widening(self) -> None:
        for mutation in [
            lambda p: p["nativeAdmission"].append("litellm"),
            lambda p: p["harbor"]["projects"].append("other-project"),
            lambda p: p["harbor"].update(roleId=1),
            lambda p: p["rancher"].update(humanSessionMinutes=960),
            lambda p: p["rancher"].update(denyExtCredentialMinting=False),
            lambda p: p["rancher"].update(groupPrincipal="genericoidc_group://homelab-owner"),
        ]:
            policy = copy.deepcopy(POLICY)
            mutation(policy)
            with self.assertRaises(ValueError):
                plan.build(fixture(), policy)

    def test_native_reconciler_retains_but_never_opens_group_admission(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "observer_admission",
            ROOT / "ansible/roles/identity_integrations/files/observer_admission.py",
        )
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        state = fixture()
        converge(state, plan.build(state, POLICY))
        for original, expected in [
            ({}, []),
            ({"allowedPrincipalIds": [guard.PRINCIPAL]}, [guard.PRINCIPAL]),
        ]:
            assert guard.retain_observer(original, [], state["globalRoles"], state["rancherSessionSetting"]) == expected
        state["rancherSessionSetting"]["value"] = "960"
        with self.assertRaisesRegex(RuntimeError, "defaults drifted"):
            guard.retain_observer(
                {"allowedPrincipalIds": [guard.PRINCIPAL]},
                [],
                state["globalRoles"],
                state["rancherSessionSetting"],
            )
        patch = guard.authconfig_patch(state["rancherAuth"], {"allowedPrincipalIds": ["preserved"]})
        assert patch[:2] == [{"op": "test", "path": "/metadata/uid", "value": "auth-uid"}, {"op": "test", "path": "/metadata/resourceVersion", "value": "9"}]

    def test_malformed_snapshot_is_a_clear_validation_error(self) -> None:
        snapshots: list[tuple[object, object]] = [
            ({}, POLICY),
            (None, POLICY),
            (fixture(), {}),
            (fixture(), None),
        ]
        for state, policy in snapshots:
            with self.assertRaises(ValueError):
                plan.build(state, policy)

    def test_harbor_group_type_and_native_entity_id_are_verified(self) -> None:
        state = fixture()
        converge(state, plan.build(state, POLICY))
        state["harbor"]["groups"] = [{"id": 101, "group_name": "homelab-observer", "group_type": 3}]
        state["harbor"]["projects"]["homelab"] = [
            {
                "id": 201,
                "entity_type": "g",
                "entity_name": "homelab-observer",
                "entity_id": 101,
                "role_id": 3,
            }
        ]
        state["harbor"]["groups"][0]["group_type"] = 1
        with self.assertRaisesRegex(ValueError, "non-OIDC"):
            plan.build(state, POLICY)
        state["harbor"]["groups"][0]["group_type"] = 3
        state["harbor"]["projects"]["homelab"][0]["entity_id"] = 999
        with self.assertRaisesRegex(ValueError, "reviewed OIDC group"):
            plan.build(state, POLICY)

    def test_unsupported_services_are_explicit_not_fake_viewers(self) -> None:
        for slug in [
            "n8n",
            "syncthing",
            "uptime-kuma",
            "open-webui",
            "3x-ui",
            "litellm",
        ]:
            assert slug in POLICY["unsupported"]
            assert slug not in POLICY["nativeAdmission"]

    def test_scripts_have_no_syntax_errors(self) -> None:
        for name in [
            "observer-access-plan.py",
            "observer-access-bootstrap.py",
            "observer-chat-migration.py",
        ]:
            ast.parse((ROOT / "scripts" / name).read_text())


class BootstrapSafetyTests(unittest.TestCase):
    """Guard observer bootstrap safety against dangerous actions."""
    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "observer_bootstrap", ROOT / "scripts/observer-access-bootstrap.py"
        )
        if spec is None or spec.loader is None:
            message = "missing observer bootstrap loader"
            raise RuntimeError(message)
        self.bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bootstrap)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.credentials = self.root / "credentials.json"
        self.credentials.write_text(
            json.dumps(
                {
                    "authentikToken": "test-only",
                    "harborUsername": "admin",
                    "harborPassword": "test-only",
                }
            )
        )
        self.credentials.chmod(0o600)
        self.state = fixture()
        self.calls: list[tuple[object, object, object]] = []
        outer = self

        class FakeClient:
            def __init__(self, credentials) -> None:
                pass

            def call(self, system, method, path, body=None):
                outer.calls.append((system, method, path))
                converge(
                    outer.state,
                    [{"system": system, "method": method, "path": path, "body": body}],
                )

        self.fake_client = FakeClient

    def run_main(self, *args: str) -> dict[str, object]:
        with (
            patch.object(self.bootstrap, "Client", self.fake_client),
            patch.object(
                self.bootstrap,
                "snapshot",
                side_effect=lambda *args: copy.deepcopy(self.state),
            ),
            patch(
                "sys.argv",
                [
                    "bootstrap",
                    "--credentials",
                    str(self.credentials),
                    "--state",
                    str(self.root / "state"),
                    *args,
                ],
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.bootstrap.main()
            receipts = json.loads(output.getvalue())
            assert isinstance(receipts, dict)
            return receipts

    def test_api_paths_are_scoped_and_reject_traversal(self) -> None:
        for system, path in [
            ("authentik", "../../etc/passwd"),
            ("harbor", "/etc/passwd"),
            ("harbor", "/api/v2.0/projects/../robots"),
            ("harbor", "/api/v2.0/projects/%252e%252e/robots"),
            ("kubernetes", "//other.example/api"),
            ("authentik", "https://other.example/core/users/"),
        ]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.bootstrap.validate_path(system, path)
        for system, path in [
            ("authentik", "core/users/?username=antropophag&page=1"),
            ("harbor", "/api/v2.0/projects/homelab/members?page=1"),
            ("kubernetes", "/apis/management.cattle.io/v3/authconfigs/genericoidc"),
        ]:
            self.bootstrap.validate_path(system, path)

    def test_explicit_harbor_machine_identity_uses_internal_config_api(self) -> None:
        header, path = self.bootstrap.harbor_authorization(
            {"harborJobserviceSecret": "test-machine-only"}
        )
        assert header == "Harbor-Secret test-machine-only"
        assert path == "/api/v2.0/internalconfig"
        header, path = self.bootstrap.harbor_authorization(
            {"harborUsername": "admin", "harborPassword": "test-only"}
        )
        assert header.startswith("Basic ")
        assert path == "/api/v2.0/configurations"
        with self.assertRaises(ValueError):
            self.bootstrap.harbor_authorization({"harborJobserviceSecret": ""})

    def test_foundation_ready_path_preserves_explicit_trusted_owner(self) -> None:
        path = Path("/home/alchemmist/.cache/homelab-authentik")
        with (
            patch.object(self.bootstrap.os, "geteuid", return_value=0),
            patch.object(self.bootstrap.pwd, "getpwnam") as user,
            patch.object(self.bootstrap, "private") as validate,
        ):
            user.return_value.pw_uid = 1000
            self.bootstrap.readiness_directory(path)
            validate.assert_called_once_with(path, directory=True, owner_uid=1000)
            validate.reset_mock()
            self.bootstrap.readiness_directory(self.root)
            validate.assert_called_once_with(self.root, directory=True, owner_uid=None)

    def test_default_is_no_native_writes(self) -> None:
        result = self.run_main()
        assert not result["applied"]
        assert self.calls == []
        assert not (self.root / "state/uncertain.json").exists()

    def test_wrong_approval_stops_before_mutation(self) -> None:
        with self.assertRaisesRegex(ValueError, "plan hash"):
            self.run_main("--apply", "--approve-plan-hash", "wrong")
        assert self.calls == []

    def test_approved_apply_private_receipts_and_native_convergence(self) -> None:
        approved = self.run_main()["plan_hash"]
        assert isinstance(approved, str)
        result = self.run_main(
            "--apply",
            "--approve-plan-hash",
            approved,
            "--authentik-directory",
            str(self.root),
        )
        assert result["applied"]
        assert not result["human_membership_changed"]
        assert plan.build(self.state, POLICY) == []
        assert not (self.root / "state/uncertain.json").exists()
        ready = self.root / "observer-ready.json"
        assert ready.stat().st_mode & 511 == 384
        assert json.loads(ready.read_text())["nativeObserverReady"]
        for receipt in (self.root / "state").glob("*/before.json"):
            assert receipt.stat().st_mode & 511 == 384

    def test_failed_write_leaves_uncertain_stop_and_no_blind_retry(self) -> None:
        approved = self.run_main()["plan_hash"]
        assert isinstance(approved, str)
        self.fake_client.call = lambda *args: (_ for _ in ()).throw(
            RuntimeError("simulated uncertain write")
        )
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            self.run_main("--apply", "--approve-plan-hash", approved)
        assert (self.root / "state/uncertain.json").exists()
        with self.assertRaisesRegex(ValueError, "Uncertain run"):
            self.run_main("--apply", "--approve-plan-hash", approved)
        assert not (self.root / "observer-ready.json").exists()


class LegacyChatMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "chat_migration", ROOT / "scripts/observer-chat-migration.py"
        )
        if spec is None or spec.loader is None:
            message = "missing observer chat migration loader"
            raise RuntimeError(message)
        self.migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.migration)

        def binding(pk, group):
            return {
                "pk": pk,
                "target": "chat-app",
                "group": group,
                "enabled": True,
                "negate": False,
                "policy": None,
                "user": None,
                "failure_result": False,
            }

        self.state: ChatState = {
            "users": [
                {
                    "username": "antropophag",
                    "uuid": POLICY["legacyChatPreservation"][0]["uuid"],
                    "pk": 92,
                    "groups": ["observer"],
                }
            ],
            "groups": [
                {"pk": "observer", "name": "homelab-observer", "users": [92]},
                {"pk": "owner", "name": "homelab-owner", "users": [1]},
            ],
            "app": {
                "pk": "chat-app",
                "slug": "open-webui",
                "provider": 7,
                "policy_engine_mode": "any",
            },
            "bindings": [
                binding("owner-binding", "owner"),
                binding("old-observer-binding", "observer"),
            ],
        }
        self.calls: list[tuple[object, object, str, object]] = []
        outer = self

        class FakeClient:
            def rows(self, path):
                if path.startswith("core/groups/"):
                    return copy.deepcopy(outer.state["groups"])
                if path.startswith("core/applications/"):
                    return [copy.deepcopy(outer.state["app"])]
                if path.startswith("policies/bindings/"):
                    return copy.deepcopy(outer.state["bindings"])
                if path.startswith("core/users/"):
                    return copy.deepcopy(outer.state["users"])
                raise AssertionError("Unexpected API read")

            def call(self, system, method, path, body=None):
                outer.calls.append((system, method, path, body))
                if method == "POST" and path == "core/groups/":
                    outer.state["groups"].append({"pk": "new-chat-group", "users": [], **body})
                elif method == "POST" and path.endswith("/add_user/"):
                    chat_user_groups = outer.state["users"][0]["groups"]
                    assert isinstance(chat_user_groups, list)
                    chat_user_groups.append("new-chat-group")
                    group_members = outer.state["groups"][-1]["users"]
                    assert isinstance(group_members, list)
                    group_members.append(92)
                elif method == "POST" and path == "policies/bindings/":
                    outer.state["bindings"].append({"pk": "new-binding", **body})
                elif method == "DELETE":
                    outer.state["bindings"] = [
                        b for b in outer.state["bindings"] if b["pk"] != path.split("/")[-2]
                    ]
                elif method == "GET" and path.startswith("core/users/"):
                    return copy.deepcopy(outer.state["users"][0])
                elif method == "GET" and path.startswith("policies/bindings/"):
                    return copy.deepcopy(
                        next(b for b in outer.state["bindings"] if b["pk"] == path.split("/")[-2])
                    )
                else:
                    raise AssertionError("Unexpected API mutation")

        self.client = FakeClient()

    def test_one_time_migration_preserves_native_subject_and_owner_then_converges(
        self,
    ) -> None:
        before = copy.deepcopy(self.state)
        operations = self.migration.build(self.state, POLICY)
        assert [op["action"] for op in operations] == ["create-chat-group", "preserve-chat-user", "admit-chat-group", "remove-observer-chat-admission"]
        for op in operations:
            self.migration.apply(self.client, op, before)
        assert self.migration.build(self.state, POLICY) == []
        assert self.state["users"][0]["uuid"] == before["users"][0]["uuid"]
        observer_groups = self.state["users"][0]["groups"]
        assert isinstance(observer_groups, list)
        assert "observer" in observer_groups
        assert self.state["bindings"][0] == before["bindings"][0]
        assert not any("password" in path or "set_password" in path for _, _, path, _ in self.calls)
        assert not any(system != "authentik" for system, _, _, _ in self.calls)
        assert [path for _, method, path, _ in self.calls if method == "DELETE"] == ["policies/bindings/old-observer-binding/"]

    def test_unreviewed_observer_or_subject_change_stops_before_writes(self) -> None:
        for modify in [
            lambda s: s["groups"][0]["users"].append(94),
            lambda s: s["users"][0].update(uuid="changed"),
            lambda s: s["users"].append(
                {"username": "danila", "uuid": "unreviewed", "pk": 94, "groups": []}
            ),
            lambda s: s["app"].update(policy_engine_mode="all"),
            lambda s: s["bindings"][0].update(negate=True),
        ]:
            state = copy.deepcopy(self.state)
            modify(state)
            with self.assertRaises(ValueError):
                self.migration.build(state, POLICY)
            assert self.calls == []

    def test_cannot_remove_legacy_admission_before_preservation(self) -> None:
        operations = self.migration.build(self.state, POLICY)
        self.migration.apply(self.client, operations[0], copy.deepcopy(self.state))
        with self.assertRaisesRegex(ValueError, "not safely admitted"):
            self.migration.apply(self.client, operations[-1], copy.deepcopy(self.state))
        assert not any(method == "DELETE" for _, method, _, _ in self.calls)

    def test_new_observer_is_not_an_ordinary_chat_user(self) -> None:
        services = json.loads((ROOT / "deploy/identity/services.json").read_text())
        assert "homelab-observer" not in services["open-webui"]["groups"]
        assert "homelab-chat-user" in services["open-webui"]["groups"]


if __name__ == "__main__":
    unittest.main()
