"""Tests for the NetBird internal network resources."""

import importlib.util
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path) -> types.ModuleType:
    """Load an offline netbird runtime module by repository path."""
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


net = load("internal_net", "scripts/netbird-internal-network.py")
owner = load("owner_guard", "scripts/netbird-owner-handover.py")
oidc = load("net_oidc", "ansible/roles/identity_integrations/files/netbird_oidc.py")


class InternalNetworkTests(unittest.TestCase):
    """Validate the internal network's exact resources and gateways."""
    def test_single_gateway_exact_resources_and_separate_local_input_gate(self) -> None:
        expected = {"10.250.0.1/32", "10.250.0.2/32", "10.250.0.3/32", "10.250.0.5/32"}
        actual = {a for _, addresses in net.NETWORKS.values() for a in addresses}
        assert actual == expected
        assert set(net.NETWORKS) == {"socrat-0"}
        with self.assertRaises(ValueError):
            net.resource_body("socrat-0", "10.250.0.1/32")
        assert net.resource_body("socrat-0", "10.250.0.1/32", local_input_authorized=True)["name"] == "wg-socrat-0"
        with self.assertRaises(ValueError):
            net.resource_body("socrat-2", "10.250.0.2/32")
        rule = net.gateway_input_policy("real-admin-jwt", "exact-gateway-api")["rules"][0]
        assert rule["sources"] == ["real-admin-jwt"]
        assert rule["destinations"] == ["exact-gateway-api"]
        assert not rule["bidirectional"]
        assert "destinationResource" not in rule
        for address in ["0.0.0.0/0", "10.250.0.0/24", "10.42.0.0/16", "192.168.0.0/24"]:
            with self.assertRaises(ValueError):
                net.resource_body("socrat-0", address)

    def test_clients_do_not_import_routes_but_serve_explicit_networks(self) -> None:
        docs = net.peers()
        assert [o["metadata"]["name"] for o in docs if o["kind"] == "Deployment"] == ["machine-socrat-0"]
        for obj in docs:
            if obj["kind"] != "Deployment":
                continue
            assert obj["spec"]["replicas"] == 0
            pod = obj["spec"]["template"]["spec"]
            assert pod["hostNetwork"]
            assert not pod["automountServiceAccountToken"]
            container = pod["containers"][0]
            assert container["resources"]["limits"]["memory"] == "96Mi"
            env = {e["name"]: e.get("value") for e in container["env"]}
            for flag in ["NB_DISABLE_CLIENT_ROUTES", "NB_DISABLE_DNS"]:
                assert env[flag] == "true"
            assert env["NB_DISABLE_SERVER_ROUTES"] == "false"
            assert env["NB_ALLOW_SERVER_SSH"] == "false"
        assert net.router_body("exact-peer")["masquerade"]

    def test_fake_api_admin_group_or_observer_group_never_accepted(self) -> None:
        for groups in [
            [],
            [{"name": net.ADMIN_GROUP, "issued": "api", "id": "fake"}],
            [{"name": "netbird-pilot-login", "issued": "jwt", "id": "observer"}],
        ]:
            with self.assertRaises(ValueError):
                net.genuine_admin_group(groups)
        assert net.genuine_admin_group([{"name": net.ADMIN_GROUP, "issued": "jwt", "id": "real"}]) == "real"
        rule = net.policy_body("real", "resource")["rules"][0]
        assert rule["sources"] == ["real"]
        assert rule["destinationResource"] == {"id": "resource", "type": "host"}
        assert not rule["bidirectional"]
        assert "All" not in str(rule)

    def test_admin_claim_not_part_of_automatic_pilot_human_grants(self) -> None:
        assert net.ADMIN_GROUP not in oidc.GROUP_NAMES
        assert net.ADMIN_GROUP in oidc.PROFILE_GROUP_NAMES
        assert net.ADMIN_GROUP in oidc.profile_expression()

    def test_owner_handover_accepts_only_one_exact_owner_device_explicitly(self) -> None:
        p = {
            "id": "mac",
            "user_id": owner.subject(),
            "approval_required": False,
            "login_expired": False,
        }

        def api(peers, policies=None):
            return lambda endpoint: (
                peers if endpoint == "peers" else (policies or []) if endpoint == "policies" else []
            )

        with self.assertRaises(ValueError):
            owner.network_snapshot(api([p]))
        assert owner.network_snapshot(api([p]), True)[0]["id"] == "mac"
        for peers in [
            [p, p],
            [dict(p, user_id="someone-else")],
            [dict(p, approval_required=True)],
            [dict(p, login_expired=True)],
        ]:
            with self.assertRaises(ValueError):
                owner.network_snapshot(api(peers), True)
        with self.assertRaises(ValueError):
            owner.network_snapshot(api([p], ["unexpected-policy"]), True)
