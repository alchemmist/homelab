"""Offline observer membership checks with fake identity clients and copied fixtures."""

import copy
import importlib.util
import os
from pathlib import Path
import sqlite3
import unittest
from typing import TypedDict
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy/platform/rancher/public-entry/files/observer_membership.py"
spec = importlib.util.spec_from_file_location("observer_membership", SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Attribute(TypedDict):
    """Rancher userattributes shape the membership plan reads and patches."""

    metadata: dict[str, str]
    ExtraByProvider: dict[str, dict[str, list[str]]]
    GroupPrincipals: dict[str, dict[str, list[dict[str, object]]]]


class AuthPatch(TypedDict):
    """Rancher auth slice exposing the observer allowance to the plan."""

    allowedPrincipalIds: list[str]


def fixture(
    subject: str = "fixture-uuid",
) -> tuple[list[dict[str, object]], list[Attribute], AuthPatch]:
    principal = m.PREFIX + subject
    user: dict[str, object] = {"metadata": {"name": "u-fixture"}, "principalIds": [principal]}
    attr: Attribute = {
        "metadata": {"name": "u-fixture", "uid": "owned", "resourceVersion": "17"},
        "ExtraByProvider": {"genericoidc": {"principalid": [principal]}},
        "GroupPrincipals": {"genericoidc": {"Items": [{"metadata": {"name": m.PRINCIPAL}}]}},
    }
    return [user], [attr], {"allowedPrincipalIds": [m.PREFIX + m.OWNER, m.PRINCIPAL]}


class MembershipTests(unittest.TestCase):
    """Native cache, wiki session, and initial cutover contracts."""

    def test_removal_is_only_cas_native_cache_update(self) -> None:
        """Replace only the observer group through compare-and-swap operations."""
        users, attrs, auth = fixture()
        before = copy.deepcopy(attrs)
        operations = m.rancher_plan(users, attrs, auth, lambda *a: False)
        assert attrs == before
        name, ops = operations[0]
        assert name == "u-fixture"
        assert [o["op"] for o in ops] == ["test", "test", "test", "test", "replace"]
        assert ops[-1] == {"op": "replace", "path": "/GroupPrincipals/genericoidc/Items", "value": []}

    def test_owner_and_reviewed_direct_principals_are_never_changed(self) -> None:
        """Leave owner and reviewed direct principals out of the cache plan."""
        for subject in [m.OWNER, "legacy-owner"]:
            users, attrs, auth = fixture(subject)
            allowed: list[str] = auth["allowedPrincipalIds"]
            allowed.append(m.PREFIX + subject)
            assert m.rancher_plan(users, attrs, auth, lambda *a: False) == []

    def test_only_observer_group_changes_and_other_groups_survive(self) -> None:
        """Drop or add only the observer group and retain an unrelated group."""
        users, attrs, auth = fixture()
        other: dict[str, object] = {
            "metadata": {"name": "genericoidc_group://other-reviewed-group"}
        }
        attrs[0]["GroupPrincipals"]["genericoidc"]["Items"].append(other)
        ops = m.rancher_plan(users, attrs, auth, lambda *a: False)[0][1]
        assert ops[-1]["value"] == [other]
        attrs[0]["GroupPrincipals"]["genericoidc"]["Items"] = [other]
        ops = m.rancher_plan(users, attrs, auth, lambda *a: True)[0][1]
        assert ops[-1]["value"][0] == other
        assert ops[-1]["value"][1]["metadata"]["name"] == m.PRINCIPAL

    def test_closed_rancher_admission_never_restores_observer_cache(self) -> None:
        """Remove the cached observer grant when Rancher admission is closed."""
        users, attrs, auth = fixture()
        auth["allowedPrincipalIds"].remove(m.PRINCIPAL)
        assert m.rancher_plan(users, attrs, auth, lambda *a: True)[0][1][-1]["value"] == []

    def test_no_native_user_provisioning_and_noop_when_converged(self) -> None:
        """Do not provision users and do nothing once the cache matches admission."""
        users, attrs, auth = fixture()
        assert m.rancher_plan(users, attrs, auth, lambda *a: True) == []
        assert m.rancher_plan([], attrs, auth, lambda *a: True) == []

    def test_wrong_subject_duplicate_and_malformed_cache_stop(self) -> None:
        """Stop on a mismatched, duplicate, or malformed observer cache."""
        for change in [
            lambda a: a["ExtraByProvider"]["genericoidc"].update(principalid=["wrong"]),
            lambda a: a["GroupPrincipals"]["genericoidc"]["Items"].append(
                copy.deepcopy(a["GroupPrincipals"]["genericoidc"]["Items"][0])
            ),
            lambda a: a["GroupPrincipals"]["genericoidc"].update(Items="wrong"),
        ]:
            users, attrs, auth = fixture()
            change(attrs[0])
            with self.assertRaises(RuntimeError):
                m.rancher_plan(users, attrs, auth, lambda *a: False)

    def test_unrelated_legacy_orphan_is_preserved_and_does_not_block_current_viewer(self) -> None:
        """Keep a legacy orphan unchanged while planning the current viewer."""
        users, attrs, auth = fixture()
        legacy_user = {"metadata": {"name": "u-old"}, "principalIds": [m.PREFIX + "old-subject"]}
        legacy_attr = {"metadata": {"name": "u-old"}, "ExtraByProvider": {}, "GroupPrincipals": {}}
        before = copy.deepcopy(legacy_attr)
        ops = m.rancher_plan([legacy_user] + users, [legacy_attr] + attrs, auth, lambda *a: False)
        assert len(ops) == 1
        assert ops[0][0] == "u-fixture"
        assert legacy_attr == before

    def test_idp_failure_cannot_produce_partial_mutations(self) -> None:
        """Propagate an identity failure before any cache mutation is planned."""
        users, attrs, auth = fixture()

        def failed(*_args):
            raise RuntimeError("IdP unavailable")

        with self.assertRaises(RuntimeError):
            m.rancher_plan(users, attrs, auth, failed)

    def test_wiki_module_matches_single_reviewed_controller_source(self) -> None:
        """Require the wiki copy to match the single reviewed controller source."""
        assert SOURCE.read_bytes() == (ROOT / "deploy/wiki-runtime/chart/files/observer_membership.py").read_bytes()

    def test_reader_gate_applies_to_cookie_and_api_tokens_not_privileged_or_unlinked_accounts(
        self,
    ) -> None:
        """Gate linked readers and leave owner, editor, and unlinked accounts."""
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE oidc_accounts(issuer TEXT,subject TEXT,user_id TEXT)")
        db.execute(
            "INSERT INTO oidc_accounts VALUES (?,?,?)", ("https://issuer/", "subject", "reader")
        )
        db.commit()

        class Store:
            """Wiki store double with owner accounts and session lookups."""

            oidc_enabled = True
            local_owners = {"owner"}

            def connect(self):
                return db

            def session(self, token):
                return {
                    "user": {
                        "id": token,
                        "role": "admin"
                        if token == "owner"
                        else "editor"
                        if token == "editor"
                        else "reader",
                    }
                }

            token_session = session

        reader = Mock()
        reader.admitted.return_value = False
        with (
            patch.dict(
                os.environ,
                {
                    "OBSERVER_IDP_READ_TOKEN_FILE": "/private/token",
                    "WIKI_OIDC_GROUP_ROLES": '{"homelab-observer":"reader"}',
                    "WIKI_OIDC_ISSUER": "https://issuer/",
                },
            ),
            patch.object(m, "MembershipReader", return_value=reader),
        ):
            store = Store()
            m.install_wiki_guard(store)
            assert store.session("reader") is None
            assert store.token_session("reader") is None
            assert store.session("owner") is not None
            assert store.session("editor") is not None
            assert store.token_session("unlinked-machine") is not None
            reader.admitted.return_value = True
            assert store.session("reader") is not None
            reader.admitted.side_effect = RuntimeError("API unavailable")
            assert store.session("reader") is None
            assert store.token_session("reader") is None
        db.close()

    def test_group_snapshot_checks_active_status_and_membership(self) -> None:
        """Admit only an active subject present in the reviewed group snapshot."""
        reader = m.MembershipReader("/unused")
        reader.rows = Mock(
            side_effect=[
                [{"pk": "g", "name": "homelab-observer"}],
                [{"uuid": "subject", "is_active": True, "groups": ["g"]}],
            ]
        )
        assert reader.admitted("subject", {"homelab-observer"})
        assert not reader.admitted("missing", {"homelab-observer"})
        reader.users["subject"]["is_active"] = False
        assert not reader.admitted("subject", {"homelab-observer"})
        assert reader.rows.call_count == 2

    def test_initial_human_cutover_is_only_reviewed_group_delta(self) -> None:
        """Plan only the reviewed observer add and readonly removal."""
        spec = importlib.util.spec_from_file_location(
            "initial_cutover", ROOT / "scripts/observer-initial-person-cutover.py"
        )
        c = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(c)
        user = {
            "pk": 94,
            "uuid": c.UUID,
            "is_active": True,
            "is_superuser": False,
            "groups": [c.READONLY, c.NETBIRD, "unrelated"],
        }
        group = {
            "pk": "observer",
            "name": "homelab-observer",
            "is_superuser": False,
            "roles": [],
            "parents": [],
        }
        before = copy.deepcopy(user)
        ops = c.plan(user, group)
        assert user == before
        assert ops == [{"path": "core/groups/observer/add_user/", "body": {"pk": 94}}, {"path": "core/groups/" + c.READONLY + "/remove_user/", "body": {"pk": 94}}]
        user["groups"] = [c.NETBIRD, "unrelated", "observer"]
        assert c.plan(user, group) == []
        user["uuid"] = "somebody-else"
        with self.assertRaises(RuntimeError):
            c.plan(user, group)

    def test_initial_cutover_records_both_steps_without_overwriting_progress(self) -> None:
        """Record both apply steps and preserve the NetBird group."""
        import tempfile, types, importlib.machinery, io, contextlib, json

        spec = importlib.util.spec_from_file_location(
            "initial_driver", ROOT / "scripts/observer-initial-person-cutover.py"
        )
        c = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(c)
        user = {
            "pk": 94,
            "uuid": c.UUID,
            "is_active": True,
            "is_superuser": False,
            "groups": [c.READONLY, c.NETBIRD],
            "password_change_date": "unchanged",
        }
        group = {
            "pk": "observer",
            "name": "homelab-observer",
            "is_superuser": False,
            "roles": [],
            "parents": [],
        }
        posts = []

        class Client:
            """Fake Authentik client that mutates only the in-memory user."""

            def __init__(self, credentials) -> None:
                pass

            def rows(self, _path):
                return [copy.deepcopy(group)]

            def call(self, _system, method, path, body=None):
                if method == "GET":
                    return copy.deepcopy(user)
                posts.append((path, body))
                if "/add_user/" in path:
                    user["groups"].append("observer")
                else:
                    user["groups"].remove(c.READONLY)

        fake = types.ModuleType("observer_bootstrap")
        fake.Client = Client
        fake.private = lambda *args, **kwargs: None
        fake.planner = types.SimpleNamespace(
            exact=lambda rows, key, value: next(x for x in rows if x[key] == value)
        )

        def exclusive_save(path, value):
            with path.open("x") as file:
                json.dump(value, file)

        fake.save = exclusive_save

        class Loader:
            """Supply the prepared bootstrap module instead of its source file."""

            def create_module(self, _spec):
                return fake

            def exec_module(self, module):
                pass

        boot_spec = importlib.machinery.ModuleSpec("observer_bootstrap", Loader())
        digest = c.fingerprint(user, group)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credentials = root / "credentials.json"
            credentials.write_text("{}")
            acceptance = root / "acceptance.json"
            acceptance.write_text(
                json.dumps(
                    {
                        "nativeObserverAcceptanceReady": True,
                        "services": ["rancher", "wiki", "argocd", "grafana"],
                        "harborGated": True,
                    }
                )
            )
            state = root / "state"
            args = [
                "cutover",
                "--credentials",
                str(credentials),
                "--state",
                str(state),
                "--acceptance",
                str(acceptance),
                "--apply",
                "--approve-plan-hash",
                digest,
            ]
            with (
                patch("sys.argv", args),
                patch.object(c.importlib.util, "spec_from_file_location", return_value=boot_spec),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                c.main()
            assert len(posts) == 2
            assert (state / "progress-1.json").exists()
            assert (state / "progress-2.json").exists()
            assert not (state / "uncertain.json").exists()
            assert set(user["groups"]) == {c.NETBIRD, "observer"}
            assert json.loads((state / "receipt.json").read_text())["netbird_preserved"]

    def test_grafana_roles_are_explicit_without_unadmitted_viewer_fallback(self) -> None:
        """Require the same strict Grafana role expression in both value files."""
        import yaml

        a = yaml.safe_load((ROOT / "deploy/identity/grafana-oidc-values.yaml").read_text())[
            "grafana"
        ]["env"]
        b = yaml.safe_load((ROOT / "charts/grafana/values.yaml").read_text())["grafana"]["env"]
        for env in [a, b]:
            assert env["GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT"] == "true"
            assert env["GF_AUTH_TOKEN_ROTATION_INTERVAL_MINUTES"] == "1"
            assert "groups" in env["GF_AUTH_GENERIC_OAUTH_SCOPES"].split()
            assert env["GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH"].endswith("|| ''")
            assert "'homelab-observer'" in env["GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH"]
        assert a["GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH"] == b["GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH"]

    def test_argo_unknown_groups_have_no_default_reader_grant_machine_reader_is_explicit(
        self,
    ) -> None:
        """Keep unknown Argo groups unassigned and the machine reader explicit."""
        for path in ["deploy/platform/argo-cd/values.yaml", "deploy/argocd/values.yaml"]:
            text = (ROOT / path).read_text()
            assert "policy.default: role:unassigned" in text
            assert "g, mcp, role:readonly" in text


if __name__ == "__main__":
    unittest.main()
