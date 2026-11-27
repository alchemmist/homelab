"""Guard the Argo-rendered loopback listener boundary."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_effective_health_fleet():
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/closed-health.yaml").read_text())[
        "spec"
    ]
    chart = ROOT / app["source"]["path"]
    (values,) = app["source"]["helm"]["valueFiles"]
    catalog = yaml.safe_load((chart / values).read_text())
    args = ["helm", "template", "closed-health", str(chart), "-f", str(chart / values)]
    assert app["destination"]["namespace"] == "public-health-staging"
    policy, config, *deployments = yaml.safe_load_all(subprocess.check_output(args))
    assert policy["kind"] == "NetworkPolicy" and policy["spec"]["ingress"] == []
    peers = []
    for rule in policy["spec"]["egress"]:
        (peer,) = rule["to"]
        peers.append(
            (
                peer["namespaceSelector"]["matchLabels"],
                peer["podSelector"]["matchLabels"],
                rule["ports"],
            )
        )
    assert peers == [
        (
            {"kubernetes.io/metadata.name": "schoolbot"},
            {
                "app.kubernetes.io/instance": "schoolbot",
                "app.kubernetes.io/name": "schoolbot",
            },
            [{"port": 8000, "protocol": "TCP"}],
        ),
        (
            {"kubernetes.io/metadata.name": "kube-system"},
            {"k8s-app": "kube-dns"},
            [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
        ),
    ]
    assert config["kind"] == "ConfigMap"
    http = yaml.safe_load(config["data"]["dynamic.yaml"])["http"]
    assert http["routers"] == {
        "health": {
            "entryPoints": ["closed"],
            "rule": "Host(`inform.sch1357.ru`) && Method(`GET`) && Path(`/api/health`)",
            "service": "schoolbot",
        }
    }
    assert http["services"]["schoolbot"]["loadBalancer"]["servers"] == [
        {"url": "http://schoolbot.schoolbot.svc.cluster.local:80"}
    ]
    placement = {}
    for deployment in deployments:
        assert deployment["kind"] == "Deployment"
        template = deployment["spec"]["template"]
        spec = template["spec"]
        assert template["metadata"]["labels"]["app"] == "closed-health"
        placement[template["metadata"]["labels"]["entrance"]] = spec["nodeSelector"][
            "kubernetes.io/hostname"
        ]
        assert not spec.get("hostNetwork") and not spec["automountServiceAccountToken"]
        assert spec["volumes"] == [
            {"name": "routes", "configMap": {"name": "closed-health"}}
        ]
        (container,) = spec["containers"]
        assert not container.get("ports")
        assert [a for a in container["args"] if a.startswith("--entrypoints")] == [
            "--entrypoints.closed.address=127.0.0.1:8181"
        ]
        assert [a for a in container["args"] if a.startswith("--providers")] == [
            "--providers.file.directory=/route"
        ]
    assert placement == {k: v["node"] for k, v in catalog["replicas"].items()}
