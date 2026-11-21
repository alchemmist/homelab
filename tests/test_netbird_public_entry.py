import base64
import datetime
import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


entry = load("nb_entry", "netbird-public-entry.py")
owner = load("nb_owner", "netbird-owner-handover.py")


class PublicEntryTests(unittest.TestCase):
    def test_scoped_identity_entry(self):
        docs = entry.manifests()
        assert all(d["metadata"]["namespace"] in ["identity", "netbird-pilot"] for d in docs)
        assert not any(
            d["kind"] in ["Secret", "ClusterRole", "Role", "IngressRoute", "Namespace"]
            for d in docs
        )
        assert "netbird-runtime" not in yaml.safe_dump_all(docs)
        deploy = next(d for d in docs if d["kind"] == "Deployment")
        assert deploy["metadata"]["name"] == "netbird-edge-forwarder"
        cm = next(d for d in docs if d["kind"] == "ConfigMap")
        static = yaml.safe_load(cm["data"]["static.yaml"])
        assert static["entryPoints"]["ping"]["address"] == ":8081"
        assert "http2" not in static["entryPoints"]["h2c"]
        dynamic = yaml.safe_load(cm["data"]["dynamic.yaml"])
        deny = dynamic["http"]["routers"]["deny-setup"]["rule"]
        for path in ["/api/setup", "/api/users/invites", "/oauth2/auth/local", "/oauth2/signup"]:
            assert path in deny
        assert "Path(`/api/setup`)" in deny
        assert "PathPrefix(`/api/setup/`)" in deny
        assert "PathPrefix(`/api/setup`)" not in deny
        for d in docs:
            if d["kind"] == "Service":
                assert "NodePort" not in str(d)
                assert "3478" not in str(d)
            if d["kind"] == "Ingress":
                assert d["spec"]["ingressClassName"] == "traefik"
                assert d["spec"]["tls"][0]["secretName"] == "netbird-pilot-tls"
        policy = next(d for d in docs if d["kind"] == "NetworkPolicy")
        rule = policy["spec"]["ingress"][1]
        assert rule["ports"] == [{"port": 80, "protocol": "TCP"}]
        assert rule["from"][0]["namespaceSelector"]["matchLabels"] == {
            "kubernetes.io/metadata.name": "identity"
        }
        assert rule["from"][0]["podSelector"]["matchLabels"] == {"app": "netbird-edge-forwarder"}

    def test_invite_list_read_does_not_enable_local_signup(self):
        cm = next(d for d in entry.manifests() if d["kind"] == "ConfigMap")
        dynamic = yaml.safe_load(cm["data"]["dynamic.yaml"])
        deny = dynamic["http"]["routers"]["deny-setup"]
        assert (
            "(PathPrefix(`/api/users/invites`) && !(Path(`/api/users/invites`) && Method(`GET`)))"
            in deny["rule"]
        )
        deny_priority = 1000
        assert deny["priority"] == deny_priority
        assert deny["middlewares"] == ["deny-unclaimed-setup"]
        assert dynamic["http"]["routers"]["api"]["service"] == "management"
        assert "PathPrefix(`/api/`)" in dynamic["http"]["routers"]["api"]["rule"]
        # No synthetic response or separate unauthenticated read router: the
        # existing native API middleware still checks bearer identity and role.
        assert "invite-list" not in dynamic["http"]["routers"]

    def test_grpc_scheme_is_on_dedicated_service_not_ingress(self):
        docs = entry.manifests()
        by_name = {(d["kind"], d["metadata"]["name"]): d for d in docs}
        key = "traefik.ingress.kubernetes.io/service.serversscheme"
        grpc = by_name["Service", "netbird-edge-forwarder-grpc"]
        web = by_name["Service", "netbird-edge-forwarder"]
        assert grpc["metadata"]["annotations"][key] == "h2c"
        assert grpc["spec"]["selector"] == web["spec"]["selector"]
        assert grpc["spec"]["ports"] == [{"name": "h2c", "port": 8082, "targetPort": "h2c"}]
        assert key not in web["metadata"].get("annotations", {})
        for name, target in [
            ("netbird-grpc", "netbird-edge-forwarder-grpc"),
            ("netbird-http", "netbird-edge-forwarder"),
        ]:
            ingress = by_name["Ingress", name]
            assert key not in ingress["metadata"]["annotations"]
            assert all(
                p["backend"]["service"]["name"] == target
                for p in ingress["spec"]["rules"][0]["http"]["paths"]
            )

    def fixture(self):
        return {
            "id": owner.subject(),
            "email": owner.EMAIL,
            "idp_id": owner.CONNECTOR,
            "is_service_user": False,
            "is_blocked": False,
            "pending_approval": False,
            "status": "active",
            "last_login": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "role": "user",
        }

    def test_exact_subject_matches_upstream_protobuf(self):
        data = base64.b64decode(owner.subject() + "==")
        assert (
            data
            == b"\n$"
            + owner.UUID.encode()
            + b"\x12"
            + bytes([len(owner.CONNECTOR)])
            + owner.CONNECTOR.encode()
        )
        assert owner.target_user([self.fixture()], owner.subject())["id"] == owner.subject()

    def test_no_uuid_connector_email_fallback(self):
        for candidate in [
            owner.EMAIL,
            owner.UUID,
            owner.subject("6015c85b-82e9-49ce-a4e3-0270c676e26d"),
            owner.subject(connector="local"),
        ]:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                owner.target_user([self.fixture()], candidate)
        for key, value in [
            ("email", "other@example.invalid"),
            ("idp_id", "local"),
            ("is_service_user", True),
            ("last_login", "0001-01-01T00:00:00Z"),
        ]:
            user = self.fixture()
            user[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                owner.target_user([user], owner.subject())
        with self.assertRaises(ValueError):
            owner.target_user([], owner.subject())


if __name__ == "__main__":
    unittest.main()
