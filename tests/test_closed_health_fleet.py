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
    blog, values = app["source"]["helm"]["valueFiles"]
    catalog = yaml.safe_load((chart / values).read_text())
    args = [
        "helm",
        "template",
        "closed-health",
        str(chart),
        "-f",
        str(chart / blog),
        "-f",
        str(chart / values),
    ]
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
            {"kubernetes.io/metadata.name": "blog"},
            {"app.kubernetes.io/instance": "blog", "app.kubernetes.io/name": "blog"},
            [{"port": 8080, "protocol": "TCP"}],
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
        "www-blog": {
            "entryPoints": ["closed"],
            "rule": "Host(`www.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": "www-blog",
        },
        "health": {
            "entryPoints": ["closed"],
            "rule": "Host(`inform.sch1357.ru`) && Method(`GET`) && Path(`/api/health`)",
            "service": "schoolbot",
        },
    }
    assert http["services"]["schoolbot"]["loadBalancer"]["servers"] == [
        {"url": "http://schoolbot.schoolbot.svc.cluster.local:80"}
    ]
    assert http["services"]["www-blog"]["loadBalancer"]["servers"] == [
        {"url": "http://blog.blog.svc.cluster.local:80"}
    ]
    # Compare the actual owner's release, not merely our own duplicate rule.
    source = yaml.safe_load((ROOT / "deploy/argocd/apps/blog.yaml").read_text())["spec"]
    chart_path = ROOT / source["source"]["path"]
    helm = source["source"]["helm"]
    assert not helm["parameters"] and source["destination"]["namespace"] == "blog"
    (release_values,) = helm["valueFiles"]
    assert (chart_path / release_values).resolve() == (chart / blog).resolve()
    owner = list(
        yaml.safe_load_all(
            subprocess.check_output(
                [
                    "helm",
                    "template",
                    helm["releaseName"],
                    str(chart_path),
                    "-n",
                    "blog",
                    "-f",
                    str(chart_path / release_values),
                ]
            )
        )
    )
    (ing,) = [d for d in owner if d and d["kind"] == "Ingress"]
    (svc,) = [d for d in owner if d and d["kind"] == "Service"]
    assert ing["spec"]["ingressClassName"] == "traefik"
    assert ing["metadata"]["labels"]["homelab.alchemmist.xyz/public-web"] == "true"
    assert set(ing["metadata"]["annotations"]) == {"cert-manager.io/cluster-issuer"}
    (www,) = [
        rule for rule in ing["spec"]["rules"] if rule["host"] == "www.alchemmist.xyz"
    ]
    assert www["http"]["paths"] == [
        {
            "path": "/",
            "pathType": "Prefix",
            "backend": {"service": {"name": "blog", "port": {"number": 80}}},
        }
    ]
    assert svc["metadata"]["name"] == "blog" and svc["spec"]["selector"] == peers[1][1]
    assert svc["spec"]["ports"] == [{"name": "http", "port": 80, "targetPort": 8080}]
    for overrides in (
        ("--set", "ingress.publicWeb=false"),
        ("--set-string", "ingress.publicWeb=true"),
        ("--set", "ingress.className=private"),
        ("--set-json", 'ingress.hosts=["alchemmist.xyz"]'),
        ("--set", "service.targetPort=9999"),
    ):
        blocked_policy, blocked_config, *unchanged = yaml.safe_load_all(
            subprocess.check_output([*args, *overrides])
        )
        assert unchanged == deployments
        assert blocked_policy["spec"]["egress"] == [
            policy["spec"]["egress"][0],
            policy["spec"]["egress"][-1],
        ]
        restricted = yaml.safe_load(blocked_config["data"]["dynamic.yaml"])["http"]
        assert restricted == {
            "routers": {"health": http["routers"]["health"]},
            "services": {"schoolbot": http["services"]["schoolbot"]},
        }
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
            "--entrypoints.closed.address=127.0.0.1:8181",
            "--entrypoints.pulse.address=127.0.0.1:8182",
        ]
        assert [a for a in container["args"] if a.startswith("--providers")] == [
            "--providers.file.directory=/route"
        ]
    assert placement == {k: v["node"] for k, v in catalog["replicas"].items()}
