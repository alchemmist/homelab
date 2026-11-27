"""Compile a loopback-only HTTP route fixture, not a public listener or egress grant."""

import subprocess

import yaml

from ci.quality.public_path_rule import source_priority
from ci.quality.public_web import CATALOG, ROOT

NS = "socrat-bot"
HOST = "bot.socrat.alchemmist.xyz"
PORT = 8080
TARGET = 8082
SELECTOR = {
    "app.kubernetes.io/name": NS,
    "app.kubernetes.io/instance": NS,
    "app.kubernetes.io/component": "bot",
}
PATHS = [
    ("/telegram", "Prefix"),
    ("/", "Exact"),
    ("/oauth/callback", "Exact"),
    ("/admin/tokens", "Prefix"),
    ("/api/v1", "Prefix"),
]


def render():
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/socrat-bot.yaml").read_text())
    chart = ROOT / "charts/socrat-bot"
    values = "../../deploy/socrat-bot/values.yaml"
    source = {
        "repoURL": "https://github.com/alchemmist/homelab.git",
        "targetRevision": "main",
        "path": "charts/socrat-bot",
        "helm": {
            "releaseName": NS,
            "valueFiles": [values],
            "parameters": [{"name": "publicWeb", "value": "true"}],
        },
    }
    if app["spec"]["source"] != source or app["spec"]["destination"] != {
        "namespace": NS,
        "server": "https://kubernetes.default.svc",
    }:
        raise ValueError("unexpected release inputs")
    return [
        obj
        for obj in yaml.safe_load_all(
            subprocess.check_output(
                [
                    "helm",
                    "template",
                    NS,
                    str(chart),
                    "-n",
                    NS,
                    "-f",
                    str(chart / values),
                    "--set-string",
                    "publicWeb=true",
                ],
                timeout=15,
            )
        )
        if obj
    ]


def fixture(objects, catalog, *, strict):
    if strict is not False or catalog["hosts"][NS] != {
        HOST: {"dns": "managed", "tlsSourceName": "socrat-bot-tls"}
    }:
        raise ValueError("unreviewed host or prefix mode")
    (ing,) = [o for o in objects if o["kind"] == "Ingress"]
    m = ing["metadata"]
    wanted = lambda o: o["metadata"]["name"] == NS and o["metadata"]["namespace"] == NS
    paths = [
        {"path": p, "pathType": k, "backend": {"service": {"name": NS, "port": {"number": PORT}}}}
        for p, k in PATHS
    ]
    if (
        not wanted(ing)
        or m["annotations"] != {"cert-manager.io/cluster-issuer": "letsencrypt-http01"}
        or m["labels"].get("homelab.alchemmist.xyz/public-web") != "true"
        or ing["spec"]
        != {
            "ingressClassName": "traefik",
            "tls": [{"hosts": [HOST], "secretName": "socrat-bot-tls"}],
            "rules": [{"host": HOST, "http": {"paths": paths}}],
        }
    ):
        raise ValueError("bot Ingress drift")
    (svc,) = [o for o in objects if o["kind"] == "Service" and wanted(o)]
    (dep,) = [o for o in objects if o["kind"] == "Deployment" and wanted(o)]
    tmpl = dep["spec"]["template"]
    pod = tmpl["spec"]
    (main,) = [c for c in pod["containers"] if c["name"] == NS]
    if (
        svc["metadata"].get("annotations")
        or svc["spec"]
        != {
            "type": "ClusterIP",
            "selector": SELECTOR,
            "ports": [{"name": "http", "port": PORT, "targetPort": TARGET}],
        }
        or dep["spec"]["selector"] != {"matchLabels": SELECTOR}
        or not SELECTOR.items() <= tmpl["metadata"]["labels"].items()
        or pod.get("hostNetwork")
        or {c["name"] for c in pod["containers"]} != {NS, "telegram-path"}
        or main["ports"] != [{"name": "http", "containerPort": TARGET}]
        or main["command"] != ["python", "-m", "socrat_bot"]
    ):
        raise ValueError("bot backend drift")
    routers = {}
    for p, kind in PATHS:
        matcher = "Path" if kind == "Exact" else "PathPrefix"
        routers["bot-" + (p.strip("/").replace("/", "-") or "root")] = {
            "rule": f"Host(`{HOST}`) && {matcher}(`{p}`)",
            "priority": source_priority(HOST, p, kind, strict_prefix=False),
            "entryPoints": ["closed"],
            "service": "bot",
        }
    return {
        "http": {
            "routers": routers,
            "services": {
                "bot": {
                    "loadBalancer": {
                        "passHostHeader": True,
                        "servers": [
                            {"url": f"http://socrat-bot.socrat-bot.svc.cluster.local:{PORT}"}
                        ],
                    }
                }
            },
        }
    }


if __name__ == "__main__":
    print(yaml.safe_dump(fixture(render(), yaml.safe_load(CATALOG.read_text()), strict=False)))
