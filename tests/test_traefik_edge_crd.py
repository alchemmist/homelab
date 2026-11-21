"""Read-only Helm render contracts for the scoped VPS CRD provider."""

from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

TRANSIT_SERVICE_PORT = 32087


class EdgeCrdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        output = subprocess.check_output(
            [
                "helm",
                "template",
                "traefik-edge",
                str(ROOT / "charts/traefik-edge"),
                "-n",
                "traefik-edge",
            ],
            text=True,
        )
        cls.resources = [d for d in yaml.safe_load_all(output) if d]

    def test_provider_is_namespace_and_label_scoped(self) -> None:
        d = next(d for d in self.resources if d["kind"] == "Deployment")
        args = d["spec"]["template"]["spec"]["containers"][0]["args"]
        assert "--providers.kubernetescrd=true" in args
        assert "--providers.kubernetescrd.namespaces=argocd" in args
        assert (
            "--providers.kubernetescrd.labelselector=homelab.alchemmist.xyz/edge-transport=argocd"
            in args
        )
        assert "--providers.kubernetescrd.allowcrossnamespace=false" in args
        assert "--providers.kubernetescrd.allowexternalnameservices=false" in args
        assert "--providers.kubernetescrd.disableclusterscoperesources=true" in args
        assert "--serverstransport.insecureskipverify=true" not in args

    def test_vpn_middleware_uses_existing_discovery_without_wider_watches(self) -> None:
        m = next(
            d
            for d in self.resources
            if d["kind"] == "Middleware" and d["metadata"]["name"] == "traefik-edge-vpn-msk-only"
        )
        assert m["metadata"]["namespace"] == "argocd"
        assert m["spec"]["ipAllowList"]["sourceRange"] == ["10.250.0.40/32", "127.0.0.1/32"]
        assert "ipStrategy" not in m["spec"]["ipAllowList"]
        ingress = next(
            d
            for d in self.resources
            if d["kind"] == "Ingress" and d["metadata"]["name"] == "traefik-edge-trojan-transit"
        )
        assert (
            ingress["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"]
            == "argocd-traefik-edge-vpn-msk-only@kubernetescrd"
        )

    def test_only_trojan_path_is_gated_not_subscription_or_panel(self) -> None:
        ingress = next(
            d
            for d in self.resources
            if d["kind"] == "Ingress" and d["metadata"]["name"] == "traefik-edge-vpn"
        )
        paths = ingress["spec"]["rules"][0]["http"]["paths"]
        assert {p["backend"]["service"]["port"]["number"] for p in paths} == {18082, 12096}
        assert (
            "traefik.ingress.kubernetes.io/router.middlewares"
            not in ingress["metadata"]["annotations"]
        )
        transit = next(
            d
            for d in self.resources
            if d["kind"] == "Ingress" and d["metadata"]["name"] == "traefik-edge-trojan-transit"
        )
        paths = transit["spec"]["rules"][0]["http"]["paths"]
        assert len(paths) == 1
        assert paths[0]["backend"]["service"]["port"]["number"] == TRANSIT_SERVICE_PORT
        assert paths[0]["pathType"] == "Exact"

    def test_new_rbac_is_argocd_read_only_and_not_cluster_wide(self) -> None:
        roles = [
            d
            for d in self.resources
            if d["kind"] == "Role" and d["metadata"]["name"] == "traefik-edge-crd"
        ]
        assert len(roles) == 1
        assert roles[0]["metadata"]["namespace"] == "argocd"
        for rule in roles[0]["rules"]:
            assert set(rule["verbs"]) == {"get", "list", "watch"}
            assert "*" not in rule["resources"]
        assert not any(
            d["kind"] == "ClusterRole" and d["metadata"]["name"].endswith("-crd")
            for d in self.resources
        )


if __name__ == "__main__":
    unittest.main()
