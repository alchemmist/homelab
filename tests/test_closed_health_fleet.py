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
    blog, fq, values = app["source"]["helm"]["valueFiles"]
    catalog = yaml.safe_load((chart / values).read_text())
    args = [
        "helm",
        "template",
        "closed-health",
        str(chart),
        "-f",
        str(chart / blog),
        "-f",
        str(chart / fq),
        "-f",
        str(chart / values),
        "--set",
        "closedFormatQuorum=true,closedWiki=true",  # exercise enabled and withdrawn shapes even after an owner opt-out
    ]
    assert app["destination"]["namespace"] == "public-health-staging"
    policy, wiki_policy, config, *deployments = yaml.safe_load_all(
        subprocess.check_output(args)
    )
    assert policy["kind"] == "NetworkPolicy" and policy["spec"]["ingress"] == []
    peers = []
    assert wiki_policy["spec"]["podSelector"] == policy["spec"]["podSelector"]
    assert wiki_policy["spec"]["policyTypes"] == ["Egress"]
    assert len(wiki_policy["spec"]["egress"]) == 1
    for rule in [
        *policy["spec"]["egress"][:-1],
        *wiki_policy["spec"]["egress"],
        policy["spec"]["egress"][-1],
    ]:
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
            {"kubernetes.io/metadata.name": "format-quorum"},
            {
                "app.kubernetes.io/instance": "format-quorum",
                "app.kubernetes.io/name": "format-quorum",
            },
            [{"port": 3000, "protocol": "TCP"}],
        ),
        (
            {"kubernetes.io/metadata.name": "wiki"},
            {
                "app.kubernetes.io/name": "hugo-docs-wiki",
                "app.kubernetes.io/instance": "wiki-runtime",
            },
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
        "wiki": {
            "entryPoints": ["closed"],
            "rule": "Host(`wiki.socrat.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": "wiki",
        },
        "format-quorum": {
            "entryPoints": ["closed"],
            "rule": "Host(`fq.alchemmist.xyz`) && PathPrefix(`/`)",
            "service": "format-quorum",
        },
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
        blocked_policy, still_wiki, blocked_config, *unchanged = yaml.safe_load_all(
            subprocess.check_output([*args, *overrides])
        )
        assert still_wiki == wiki_policy
        assert unchanged == deployments
        assert blocked_policy["spec"]["egress"] == [
            policy["spec"]["egress"][0],
            *policy["spec"]["egress"][2:],
        ]
        restricted = yaml.safe_load(blocked_config["data"]["dynamic.yaml"])["http"]
        assert restricted == {
            "routers": {k: v for k, v in http["routers"].items() if k != "www-blog"},
            "services": {k: v for k, v in http["services"].items() if k != "www-blog"},
        }
    policy_off, separate_wiki, config_off, *unchanged = yaml.safe_load_all(
        subprocess.check_output(
            [
                *args[:-2],
                "--set",
                "closedWiki=true",
                "--set-string",
                "closedFormatQuorum=true",
            ]
        )
    )
    assert unchanged == deployments
    assert policy_off["spec"]["egress"] == [
        r for i, r in enumerate(policy["spec"]["egress"]) if i != 2
    ]
    after = yaml.safe_load(config_off["data"]["dynamic.yaml"])["http"]
    for section in ("routers", "services"):
        assert after[section] == {
            k: v for k, v in http[section].items() if k != "format-quorum"
        }
    policy_off, separate_wiki, config_off, *unchanged = yaml.safe_load_all(
        subprocess.check_output([*args, "--set", "closedWiki=false"])
    )
    assert unchanged == deployments and policy_off == policy
    assert separate_wiki["spec"] == {**wiki_policy["spec"], "egress": []}
    off = yaml.safe_load(config_off["data"]["dynamic.yaml"])["http"]
    for section in ("routers", "services"):
        assert off[section] == {k: v for k, v in http[section].items() if k != "wiki"}
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


def test_format_quorum_admission_matches_owner_release():
    from ci.quality.closed_root_owners import OUTPUT, render

    assert OUTPUT.read_text() == render()


def test_format_quorum_withdraws_unreviewed_owner_changes():
    from copy import deepcopy

    from ci.quality.closed_root_owners import APP, CATALOG, eligible

    command = [
        "helm",
        "template",
        APP,
        str(ROOT / "charts" / APP),
        "-n",
        APP,
        "-f",
        str(ROOT / "deploy" / APP / "values.yaml"),
        "--set",
        "ingress.publicWeb=true",
    ]
    rows = [r for r in yaml.safe_load_all(subprocess.check_output(command)) if r]
    catalog = yaml.safe_load(CATALOG.read_text())
    assert eligible(rows, catalog)
    for kind, mutate in [
        ("Ingress", lambda i: i["metadata"]["labels"].clear()),
        (
            "Ingress",
            lambda i: i["metadata"]["annotations"].update(
                {"traefik.ingress.kubernetes.io/router.middlewares": "auth"}
            ),
        ),
        ("Ingress", lambda i: i["spec"]["rules"][0]["http"]["paths"].clear()),
        ("Service", lambda s: s["spec"].update({"type": "ExternalName"})),
        ("Service", lambda s: s["spec"]["ports"][0].update({"targetPort": 80})),
    ]:
        changed = deepcopy(rows)
        mutate(next(r for r in changed if r["kind"] == kind))
        assert not eligible(changed, catalog)
    assert not eligible([*rows, {"kind": "HTTPRoute"}], catalog)


def test_wiki_requires_public_runtime_and_unmodified_named_backend():
    from copy import deepcopy

    from ci.quality.closed_root_owners import CATALOG, eligible, owner_render

    rows = owner_render(wiki=True)
    catalog = yaml.safe_load(CATALOG.read_text())
    for kind, change in [
        (
            "Deployment",
            lambda r: next(
                x
                for x in r["spec"]["template"]["spec"]["containers"][0]["env"]
                if x["name"] == "WIKI_PUBLIC"
            ).update(value="false"),
        ),
        (
            "Deployment",
            lambda r: r["spec"]["template"]["spec"]["containers"][0]["ports"][0].update(
                containerPort=9999
            ),
        ),
        ("Service", lambda r: r["metadata"].update(namespace="private")),
        ("Ingress", lambda r: r["metadata"]["labels"].clear()),
        (
            "Ingress",
            lambda r: r["metadata"]["annotations"].update(
                {"traefik.ingress.kubernetes.io/router.middlewares": "auth"}
            ),
        ),
    ]:
        changed = deepcopy(rows)
        change(next(d for d in changed if d["kind"] == kind))
        assert not eligible(changed, catalog, wiki=True)
    chart = ROOT / "deploy/wiki-runtime/chart"
    raw = subprocess.check_output(
        [
            "helm",
            "template",
            "wiki-runtime",
            str(chart),
            "-n",
            "wiki",
            "-f",
            str(chart / "../values.yaml"),
            "--set",
            "visibility=private",
        ]
    )
    assert not eligible([r for r in yaml.safe_load_all(raw) if r], catalog, wiki=True)
