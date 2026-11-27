"""Compile Harbor's complete TLS-only route set from its reviewed Helm release.

Offline fixture input, not authorization to publish, grant backend egress or read keys.
The caller must separately establish both the original prefix mode and exclusivity
of the host across providers. Never publish a partial result on rejection.
"""

import sys

import yaml
from ci.quality.public_path_rule import source_priority
from ci.quality.public_web import CATALOG, ROOT

HOST = "harbor.socrat.alchemmist.xyz"
PATHS = {"/api/": "core", "/service/": "core", "/v2/": "core", "/c/": "core", "/": "portal"}
ANNOTATIONS = {
    "cert-manager.io/cluster-issuer": "letsencrypt-http01",
    "ingress.kubernetes.io/proxy-body-size": "0",
    "ingress.kubernetes.io/ssl-redirect": "true",
    "nginx.ingress.kubernetes.io/proxy-body-size": "0",
    "nginx.ingress.kubernetes.io/ssl-redirect": "true",
    "traefik.ingress.kubernetes.io/router.entrypoints": "websecure",
    "traefik.ingress.kubernetes.io/router.tls": "true",
}
FILES = ["../../deploy/platform/harbor/values.yaml", "../../deploy/platform/harbor/pg-common.yaml"]


def owner_command() -> list[str]:
    """Return the exact offline Helm command after checking the Argo release inputs."""
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/harbor.yaml").read_text())
    src = app["spec"]["source"]
    if (
        app["metadata"]["name"] != "harbor"
        or app["spec"]["destination"]
        != {"namespace": "harbor", "server": "https://kubernetes.default.svc"}
        or src
        != {
            "repoURL": "https://github.com/alchemmist/homelab.git",
            "targetRevision": "main",
            "path": "charts/harbor",
            "helm": {"releaseName": "harbor", "valueFiles": FILES},
        }
    ):
        message = "unexpected Harbor release inputs"
        raise ValueError(message)
    chart = ROOT / src["path"]
    args = ["helm", "template", "harbor", str(chart), "-n", "harbor"]
    for f in FILES:
        args += ["-f", str(chart / f)]
    return args


def compile_fixture(objects: list[dict], catalog: dict, *, source_strict: bool) -> dict:
    """Reject the entire host when any reviewed path or destination changes."""
    if source_strict is not False or catalog["hosts"].get("harbor", {}).get(HOST) != {
        "dns": "managed",
        "tlsSourceName": "harbor-tls",
    }:
        message = "unreviewed Harbor host or prefix mode"
        raise ValueError(message)
    ings = [d for d in objects if d["kind"] == "Ingress"]
    expected = [
        {
            "path": p,
            "pathType": "Prefix",
            "backend": {"service": {"name": "harbor-" + target, "port": {"number": 80}}},
        }
        for p, target in PATHS.items()
    ]
    if len(ings) != 1:
        message = "unexpected Harbor ingress set"
        raise ValueError(message)
    ing = ings[0]
    meta = ing["metadata"]
    spec = ing["spec"]
    if (
        meta["name"] != "harbor-ingress"
        or meta.get("namespace", "harbor") != "harbor"
        or meta.get("annotations") != ANNOTATIONS
        or meta.get("labels", {}).get("homelab.alchemmist.xyz/public-web") != "true"
        or spec
        != {
            "ingressClassName": "traefik",
            "tls": [{"hosts": [HOST], "secretName": "harbor-tls"}],
            "rules": [{"host": HOST, "http": {"paths": expected}}],
        }
    ):
        message = "Harbor routing or TLS contract changed"
        raise ValueError(message)
    services = {}
    for target in ("core", "portal"):
        name = "harbor-" + target
        rows = [d for d in objects if d["kind"] == "Service" and d["metadata"]["name"] == name]
        port = {"port": 80, "targetPort": 8080}
        selector = {"release": "harbor", "app": "harbor", "component": target}
        if target == "core":
            port["name"] = "http-web"
        if (
            len(rows) != 1
            or rows[0]["metadata"].get("namespace", "harbor") != "harbor"
            or rows[0]["metadata"].get("annotations")
            or rows[0]["spec"] != {"ports": [port], "selector": selector}
        ):
            message = "unreviewed Harbor Service"
            raise ValueError(message)
        services[name] = {
            "loadBalancer": {
                "passHostHeader": True,
                "servers": [{"url": f"http://{name}.harbor.svc.cluster.local:80"}],
            }
        }
    routers = {}
    for path, target in PATHS.items():
        rule = f"Host(`{HOST}`) && PathPrefix(`{path}`)"
        routers["harbor-" + (path.strip("/") or "portal")] = {
            "rule": rule,
            "priority": source_priority(HOST, path, "Prefix", strict_prefix=False),
            "entryPoints": ["closedsecure"],
            "tls": {},
            "service": "harbor-" + target,
        }
    return {"http": {"routers": routers, "services": services}}


if __name__ == "__main__":
    owner_command()
    # Feed the output of owner_command() on stdin; never accept live keys.
    render = [obj for obj in yaml.safe_load_all(sys.stdin) if obj]
    yaml.safe_dump(
        compile_fixture(render, yaml.safe_load(CATALOG.read_text()), source_strict=False),
        sys.stdout,
    )
