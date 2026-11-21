import copy
import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("netbird_access", ROOT / "scripts/netbird-access.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def _mapping(value: object) -> dict[str, object]:
    """Return the assert-verified mapping view of a parsed snapshot value."""
    assert isinstance(value, dict)
    result: dict[str, object] = value
    return result


def _documents(value: object) -> list[dict[str, object]]:
    """Return the assert-verified list-of-mappings view of a parsed snapshot value."""
    assert isinstance(value, list)
    documents: list[dict[str, object]] = value
    return documents


def _sequence(value: object) -> list[object]:
    """Return the assert-verified list view of a parsed snapshot value."""
    assert isinstance(value, list)
    sequence: list[object] = value
    return sequence


def snapshot() -> dict[str, object]:
    """Build the reviewed management-plane snapshot used by the offline tests."""
    s: dict[str, object] = {
        "nb_accounts": [
            {
                "id": "account",
                "settings": {
                    "local_auth_disabled": True,
                    "jwt_groups_enabled": True,
                    "groups_propagation_enabled": True,
                    "jwt_groups_claim_name": "groups",
                    "jwt_allow_groups": [M.LEGACY_LOGIN],
                    "peer_login_expiration": 28800,
                    "extra": {"user_approval_required": True, "peer_approval_enabled": False},
                },
            }
        ],
        "nb_groups": [
            {"id": "all", "name": "All", "issued": "api"},
            {"id": "admins", "name": M.ADMIN, "issued": "jwt"},
        ],
        "nb_dns": {"disabled_management_groups": []},
        "nb_policies": [
            {
                "enabled": True,
                "rules": [{"enabled": True, "sources": ["admins"], "destinations": ["nodes"]}],
            }
        ],
        "ak_groups": [
            {
                "pk": "admins",
                "name": M.ADMIN,
                "users": [1],
                "is_superuser": False,
                "parents": [],
                "roles": [],
            },
            {"pk": "login", "name": M.LEGACY_LOGIN},
        ],
        "ak_apps": [{"slug": M.APP, "pk": "app", "provider": 1, "policy_engine_mode": "any"}],
        "ak_providers": [
            {
                "pk": 1,
                "sub_mode": "user_uuid",
                "authentication_flow": "mfa",
                "authorization_flow": "authorization",
                "property_mappings": ["openid", "email", "profile"],
            }
        ],
        "ak_mfa": [{"pk": "mfa", "not_configured_action": "configure"}],
        "ak_flow_bindings": [{"stage": "mfa"}],
        "ak_scopes": [
            {
                "pk": "groups",
                "name": M.PROFILE_MAPPING,
                "scope_name": "profile",
                "expression": M.EXPRESSION,
            }
        ],
        "ak_bindings": [{"group": "login", "enabled": True, "order": 0}],
        "ak_users": [
            {
                "pk": 2,
                "uuid": "exact-reviewed-uuid",
                "username": "new-admin",
                "is_active": True,
                "is_superuser": False,
                "type": "internal",
                "groups": ["unrelated"],
            }
        ],
    }
    return s


class AdmissionTests(unittest.TestCase):
    def test_reconcile_is_additive_and_preserves_session_policy(self) -> None:
        s = snapshot()
        before = copy.deepcopy(s)
        plan = M.reconcile_plan(s)
        assert s == before
        assert len(plan) == 4
        assert plan[0]["body"]["property_mappings"] == ["openid", "email", "profile", "groups"]
        account = next(p for p in plan if p["purpose"] == "trusted-group-sso-admission")
        assert account["body"]["settings"]["peer_login_expiration"] == 28800
        assert account["body"]["settings"]["jwt_allow_groups"] == [M.LEGACY_LOGIN, M.ADMIN]
        dns = next(p for p in plan if p["purpose"] == "server-side-dns-management-off")
        assert dns["body"]["disabled_management_groups"] == ["all"]

    def test_reconcile_noop_after_expected_readback(self) -> None:
        s = snapshot()
        _sequence(
            _mapping(_documents(s["ak_providers"])[0])["property_mappings"]
        ).append("groups")
        _documents(s["ak_bindings"]).append({"group": "admins", "enabled": True, "order": 1})
        _sequence(
            _mapping(_mapping(_documents(s["nb_accounts"])[0])["settings"])["jwt_allow_groups"]
        ).append(M.ADMIN)
        _mapping(
            _mapping(_mapping(_documents(s["nb_accounts"])[0])["settings"])["extra"]
        )["user_approval_required"] = False
        _mapping(s["nb_dns"])["disabled_management_groups"] = ["all"]
        assert M.reconcile_plan(s) == []

    def test_vendor_scope_gap_creates_profile_mapping_without_fake_groups(self) -> None:
        s = snapshot()
        s["ak_scopes"] = []
        plan = M.reconcile_plan(s)
        assert plan[0]["body"]["scope_name"] == "profile"
        assert plan[0]["body"]["expression"] == M.EXPRESSION
        assert plan[1]["body"]["property_mappings"][-1] == "$profile_mapping"

    def test_auto_admission_remains_group_restricted_and_preserves_peer_policy(self) -> None:
        s = snapshot()
        plan = M.reconcile_plan(s)
        change = next(p for p in plan if p["purpose"] == "trusted-group-sso-admission")
        assert not change["body"]["settings"]["extra"]["user_approval_required"]
        assert not change["body"]["settings"]["extra"]["peer_approval_enabled"]
        _sequence(
            _mapping(_mapping(_documents(s["nb_accounts"])[0])["settings"])["jwt_allow_groups"]
        ).append("unreviewed-public-signup")
        with self.assertRaises(ValueError):
            M.reconcile_plan(s)

    def test_missing_or_skipping_mfa_blocks_admission(self) -> None:
        s = snapshot()
        s["ak_flow_bindings"] = []
        with self.assertRaises(ValueError):
            M.reconcile_plan(s)
        s = snapshot()
        _documents(s["ak_mfa"])[0]["not_configured_action"] = "skip"
        with self.assertRaises(ValueError):
            M.reconcile_plan(s)

    def test_default_all_policy_blocks_onboarding(self) -> None:
        s = snapshot()
        _mapping(_documents(_documents(s["nb_policies"])[0]["rules"])[0])["sources"] = ["all"]
        with self.assertRaises(ValueError):
            M.reconcile_plan(s)
        s = snapshot()
        _mapping(_documents(_documents(s["nb_policies"])[0]["rules"])[0])["destinations"] = [
            {"id": "all"}
        ]
        with self.assertRaises(ValueError):
            M.reconcile_plan(s)

    def test_fake_jwt_source_rejected(self) -> None:
        s = snapshot()
        _documents(s["nb_groups"])[1]["issued"] = "api"
        with self.assertRaises(ValueError):
            M.reconcile_plan(s)

    def test_superuser_or_parent_group_rejected(self) -> None:
        for key, value in [
            ("is_superuser", True),
            ("parents", ["owner"]),
            ("roles", ["administrator"]),
        ]:
            with self.subTest(key=key):
                s = snapshot()
                _documents(s["ak_groups"])[0][key] = value
                with self.assertRaises(ValueError):
                    M.reconcile_plan(s)

    def test_unexpected_app_bypass_rejected(self) -> None:
        for binding in [
            {"group": "unknown", "enabled": True},
            {"group": "login", "enabled": True, "user": 12},
            {"group": "login", "enabled": True, "failure_result": True},
        ]:
            s = snapshot()
            s["ak_bindings"] = [binding]
            with self.assertRaises(ValueError):
                M.reconcile_plan(s)

    def test_membership_action_never_replaces_other_groups_or_grants_superuser(self) -> None:
        s = snapshot()
        plan = M.membership_plan(s, "new-admin", "exact-reviewed-uuid")
        assert plan[0]["path"] == "core/groups/admins/add_user/"
        assert plan[0]["body"] == {"pk": 2}
        assert _documents(s["ak_users"])[0]["groups"] == ["unrelated"]
        assert len(plan) == 1

    def test_no_email_fallback_or_ambiguous_adoption(self) -> None:
        s = snapshot()
        with self.assertRaises(ValueError):
            M.membership_plan(s, "new-admin", "wrong-uuid")
        users = _documents(s["ak_users"])
        users.append(dict(users[0]))
        with self.assertRaises(ValueError):
            M.membership_plan(s, "new-admin", "exact-reviewed-uuid")

    def test_nonhuman_inactive_superuser_rejected(self) -> None:
        for key, value in [
            ("type", "service_account"),
            ("is_active", False),
            ("is_superuser", True),
        ]:
            s = snapshot()
            _documents(s["ak_users"])[0][key] = value
            with self.assertRaises(ValueError):
                M.membership_plan(s, "new-admin", "exact-reviewed-uuid")

    def test_membership_grant_revoke_idempotence(self) -> None:
        s = snapshot()
        assert M.membership_plan(s, "new-admin", "exact-reviewed-uuid", True) == []
        _sequence(_mapping(_documents(s["ak_groups"])[0])["users"]).append(2)
        assert M.membership_plan(s, "new-admin", "exact-reviewed-uuid") == []
        assert "remove_user" in M.membership_plan(s, "new-admin", "exact-reviewed-uuid", True)[0]["path"]

    def test_prior_uncertain_receipt_blocks_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            p = root / "run"
            p.mkdir()
            M.atomic(p / "receipt.json", {"state": "uncertain-stop"})
            with self.assertRaises(ValueError):
                M.check_state_folder(root)

    def offboard_state(self) -> dict[str, object]:
        """Build the reviewed connected-state snapshot used by offboarding tests."""
        s = snapshot()
        _mapping(_documents(s["ak_providers"])[0])["client_id"] = "reviewed-client"
        s["nb_idps"] = [
            {
                "id": "authentik-reviewed-connector",
                "type": "authentik",
                "issuer": "https://auth.socrat.alchemmist.xyz/application/o/" + M.APP + "/",
                "client_id": "reviewed-client",
            }
        ]
        uid = b"exact-reviewed-uuid"
        connector = b"authentik-reviewed-connector"
        subject = (
            base64.b64encode(bytes([10, len(uid)]) + uid + bytes([18, len(connector)]) + connector)
            .decode()
            .rstrip("=")
        )
        s["nb_users"] = [
            {
                "id": subject,
                "idp_id": connector.decode(),
                "role": "user",
                "is_service_user": False,
                "is_blocked": False,
                "auto_groups": ["unrelated"],
            }
        ]
        s["nb_peers"] = [
            {"id": "target-peer", "user_id": subject},
            {"id": "untouched-machine", "user_id": "service"},
        ]
        _sequence(_mapping(_documents(s["ak_groups"])[0])["users"]).append(2)
        return s

    def test_offboarding_blocks_login_and_retires_only_exact_subject_devices(self) -> None:
        s = self.offboard_state()
        plan = M.offboard_plan(s, "new-admin", "exact-reviewed-uuid")
        assert plan[0]["body"]["is_blocked"]
        assert plan[1]["path"] == "peers/target-peer"
        assert "remove_user" in plan[2]["path"]
        assert "untouched-machine" not in str(plan)

    def test_owner_or_foreign_connector_offboarding_is_refused(self) -> None:
        s = self.offboard_state()
        _documents(s["nb_users"])[0]["role"] = "owner"
        with self.assertRaises(ValueError):
            M.offboard_plan(s, "new-admin", "exact-reviewed-uuid")
        s = self.offboard_state()
        _documents(s["nb_idps"])[0]["client_id"] = "unexpected"
        with self.assertRaises(ValueError):
            M.offboard_plan(s, "new-admin", "exact-reviewed-uuid")

    def test_already_disabled_authentik_user_can_still_be_offboarded(self) -> None:
        s = self.offboard_state()
        _documents(s["ak_users"])[0]["is_active"] = False
        assert M.offboard_plan(s, "new-admin", "exact-reviewed-uuid")

    def test_offboard_noop_after_readback(self) -> None:
        s = self.offboard_state()
        _documents(s["nb_users"])[0]["is_blocked"] = True
        s["nb_peers"] = []
        users = _sequence(_mapping(_documents(s["ak_groups"])[0])["users"])
        assert 2 in users
        users.remove(2)
        assert M.offboard_plan(s, "new-admin", "exact-reviewed-uuid") == []

    def test_no_password_setup_key_or_kubernetes_mutations(self) -> None:
        actions = str(M.reconcile_plan(snapshot())) + str(
            M.membership_plan(snapshot(), "new-admin", "exact-reviewed-uuid")
        )
        for forbidden in [
            "password",
            "setup-key",
            "cluster-admin",
            "is_superuser",
            "kubectl",
            "users/invites",
        ]:
            assert forbidden not in actions
