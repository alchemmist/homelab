import importlib.util
from pathlib import Path
import types
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / "scripts" / (name + ".py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("missing script loader for " + name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mesh = load("netbird-redundant-access")
relay = load("netbird-independent-relay")
dns = load("netbird-macos-bootstrap-dns")
base = load("netbird-host-peer")


class IndependentAccessTest(unittest.TestCase):
    def test_four_exact_hosts_opt_in_no_implicit_enrollment(self) -> None:
        docs = mesh.manifests()
        assert len(docs) == 8
        for host in mesh.HOSTS:
            pvc, deploy = mesh.peer(host)
            assert deploy["spec"]["replicas"] == 0
            spec = deploy["spec"]["template"]["spec"]
            assert spec["nodeSelector"] == {"kubernetes.io/hostname": host}
            assert spec["hostNetwork"]
            env = {e["name"]: e.get("value") for e in spec["containers"][0]["env"]}
            assert env["NB_DISABLE_SERVER_ROUTES"] == "false"
            assert env["NB_DISABLE_CLIENT_ROUTES"] == "true"
            assert env["NB_DISABLE_DNS"] == "true"
            assert "@sha256:" in spec["containers"][0]["image"]
        with self.assertRaises(ValueError):
            base.peer("socrat-1")
        with self.assertRaises(ValueError):
            mesh.peer("new-vm")

    def test_native_group_router_not_single_peer_or_default_route(self) -> None:
        assert mesh.router_body("exact-node-group") == {"peer_groups": ["exact-node-group"], "enabled": True, "masquerade": True, "metric": 80}
        assert set(mesh.NODE_ADDRESSES.values()) == {"10.250.0.1/32", "10.250.0.2/32", "10.250.0.3/32", "10.250.0.5/32"}
        for bad in [None, "", "All", "default", [], "group/other", "group name"]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mesh.router_body(bad)

    def test_distinct_input_policies_keep_pilot_tcp_only(self) -> None:
        admin = mesh.admin_input_policy("jwt-admin", "nodes")["rules"][0]
        pilot = mesh.pilot_input_policy("jwt-pilot", "only-node2")["rules"][0]
        assert admin["sources"] == ["jwt-admin"]
        assert admin["destinations"] == ["nodes"]
        assert not admin["bidirectional"]
        assert admin["protocol"] == "all"
        assert pilot["sources"] == ["jwt-pilot"]
        assert pilot["destinations"] == ["only-node2"]
        assert pilot["protocol"] == "tcp"
        assert pilot["ports"] == ["2222"]
        for fn in [mesh.admin_input_policy, mesh.pilot_input_policy]:
            for args in [("same", "same"), ("All", "nodes"), ("jwt", "default"), ([], "nodes")]:
                with self.assertRaises(ValueError):
                    fn(*args)

    def test_relay_pinned_vps_and_no_secret_values_or_management(self) -> None:
        docs = relay.manifests()
        assert [d["kind"] for d in docs] == ["Deployment", "Service", "NetworkPolicy", "Certificate", "Ingress"]
        pod = docs[0]["spec"]["template"]["spec"]
        assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-2"}
        assert not pod["automountServiceAccountToken"]
        assert "hostNetwork" not in pod
        container = pod["containers"][0]
        assert "@sha256:" in container["image"]
        assert container["resources"]["limits"]["memory"] == "64Mi"
        assert container["readinessProbe"]["httpGet"] == {"path": "/health", "port": 9000}
        env = {e["name"]: e for e in container["env"]}
        assert env["NB_ENABLE_STUN"]["value"] == "false"
        assert "value" not in env["NB_AUTH_SECRET"]
        assert container["securityContext"]["readOnlyRootFilesystem"]
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
        ingress = docs[-1]["spec"]
        assert ingress["rules"][0]["http"]["paths"][0]["path"] == "/relay"
        assert ingress["rules"][0]["http"]["paths"][0]["pathType"] == "Exact"
        assert "/api" not in yaml.safe_dump(docs)

    def test_native_self_health_bootstrap_and_actual_vps_cni(self) -> None:
        service, policy = relay.manifests()[1:3]
        assert service["spec"]["publishNotReadyAddresses"]
        assert service["metadata"]["annotations"]["traefik.ingress.kubernetes.io/service.nativelb"] == "true"
        ingress = policy["spec"]["ingress"][0]
        cidrs = {source["ipBlock"]["cidr"] for source in ingress["from"]}
        assert "10.42.0.1/32" in cidrs
        assert "10.42.2.1/32" not in cidrs
        assert "0.0.0.0/0" not in cidrs
        assert ingress["ports"] == [{"protocol": "TCP", "port": 33080}]

    def test_home_relay_is_separate_and_reuses_existing_tls(self) -> None:
        deploy, service, policy, ingress = relay.home_manifests()
        assert deploy["spec"]["template"]["spec"]["nodeSelector"] == {"kubernetes.io/hostname": "socrat-0"}
        assert service["spec"]["selector"] == {"app": "netbird-relay-home"}
        assert service["spec"]["publishNotReadyAddresses"]
        assert ingress["spec"]["tls"][0]["secretName"] == "netbird-pilot-tls"
        assert ingress["spec"]["rules"][0]["host"] == "netbird.socrat.alchemmist.xyz"
        sources = policy["spec"]["ingress"][0]["from"]
        assert "10.42.0.0/32" in {s["ipBlock"]["cidr"] for s in sources if "ipBlock" in s}
        assert sources[0]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "traefik"}
        assert sources[0]["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "kube-system"}
        assert relay.advertised_relays()["addresses"] == [relay.URI, relay.HOME_URI]
        assert relay.advertised_relays()["credentialsTTL"] == "12h"
        assert "relay" not in relay.advertised_relays()

    def test_mac_bootstrap_does_not_depend_on_internal_dns(self) -> None:
        assert len(dns.HOSTS) == 3
        assert "auth.socrat.alchemmist.xyz" in dns.HOSTS
        body = dns.render().decode()
        assert "10.250." not in body
        assert "nameserver 1.1.1.1\n" in body
        assert "nameserver 9.9.9.9\n" in body
        assert "socrat.alchemmist.xyz" not in body  # no broad resolver rewrite


if __name__ == "__main__":
    unittest.main()
