"""Compile narrowly reviewed root HTTP admissions from the owner's complete Argo render."""

import argparse
import subprocess

import yaml

from ci.quality.closed_status_owner import render_status
from ci.quality.public_web import CATALOG, ROOT

APP = "format-quorum"
HOST = "fq.alchemmist.xyz"
PIN = "format-quorum-tls"
OUTPUT = ROOT / "deploy/public-web/closed-root-owners.yaml"


# Namespace, resource name, approved host, pin, Service port, upstream port,
# target Pod selector. This table is reviewed; a new label cannot add entries.
ROOTS = {
    **{
        app: (
            app,
            app,
            app + ".alchemmist.xyz",
            app + "-tls",
            80,
            "http" if app == "wishlist" else 8000,
            {"app.kubernetes.io/name": app, "app.kubernetes.io/instance": app},
        )
        for app in ("lms", "wishlist")
    },
    APP: (
        APP,
        APP,
        HOST,
        PIN,
        80,
        3000,
        {"app.kubernetes.io/name": APP, "app.kubernetes.io/instance": APP},
    ),
    "wiki-runtime": (
        "wiki",
        "wiki-runtime-wiki",
        "wiki.socrat.alchemmist.xyz",
        "wiki-tls",
        8080,
        "http",
        {"app.kubernetes.io/name": "hugo-docs-wiki", "app.kubernetes.io/instance": "wiki-runtime"},
    ),
    "monori": (
        "monori",
        "monori",
        "monori.alchemmist.xyz",
        "monori-tls",
        80,
        "http",
        {"app": "monori"},
    ),
}


def eligible(items, catalog, *, owner=APP):
    """Only translate the complete reviewed root matcher and exact upstream contract."""
    ns, name, host, pin, svc_port, target_port, selector = ROOTS[owner]
    wiki = owner == "wiki-runtime"
    if catalog["hosts"].get(ns, {}).get(host) != {"dns": "managed", "tlsSourceName": pin}:
        return False
    owners = [d for d in items if d["kind"] == "Ingress"]
    services = [d for d in items if d["kind"] == "Service" and d["metadata"]["name"] == name]
    if (
        len(owners) != 1
        or len(services) != 1
        or any(
            d["kind"] in {"IngressRoute", "HTTPRoute", "IngressRouteTCP", "TLSRoute"} for d in items
        )
    ):
        return False
    ing, svc = owners[0], services[0]
    if any(
        d["metadata"]["name"] != name or d["metadata"].get("namespace", ns if wiki else None) != ns
        for d in (ing, svc)
    ):
        return False
    if (target_port == "http" or owner == "lms") and not _named_runtime(
        items, ns, name, selector, host, wiki=wiki
    ):
        return False
    port = {"name": "http"} if wiki else {"number": 80}
    return (
        ing["apiVersion"] == "networking.k8s.io/v1"
        and svc["apiVersion"] == "v1"
        and ing["metadata"].get("labels", {}).get("homelab.alchemmist.xyz/public-web") == "true"
        and ing["metadata"].get("annotations")
        == {"cert-manager.io/cluster-issuer": "letsencrypt-http01"}
        and ing["spec"]
        == {
            "ingressClassName": "traefik",
            "tls": [{"hosts": [host], "secretName": pin}],
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {"service": {"name": name, "port": port}},
                            }
                        ]
                    },
                }
            ],
        }
        and not svc["metadata"].get("annotations")
        and svc["spec"]
        == {
            "selector": selector,
            "ports": [
                {
                    "name": "http",
                    "port": svc_port,
                    "targetPort": target_port,
                },
                *(
                    [{"name": "metrics", "port": 8001, "targetPort": "metrics"}]
                    if owner == "wishlist"
                    else []
                ),
            ],
        }
    )


def _named_runtime(items, ns, name, selector, host, *, wiki):
    workloads = [
        d
        for d in items
        if d["kind"] in {"Deployment", "DaemonSet", "StatefulSet", "Job", "ReplicaSet"}
        and d["metadata"].get("namespace", ns) == ns
        and all(
            d["spec"]["template"].get("metadata", {}).get("labels", {}).get(k) == v
            for k, v in selector.items()
        )
    ]
    if (
        len(workloads) != 1
        or workloads[0]["kind"] != "Deployment"
        or workloads[0]["metadata"]["name"] != name
    ):
        return False
    template = workloads[0]["spec"]["template"]
    pod = template["spec"]
    containers = pod["containers"]
    if template["metadata"]["labels"] != selector or pod.get("hostNetwork") or len(containers) != 1:
        return False
    c = containers[0]
    if ns == "wishlist":
        return c["name"] == ns and c.get("ports") == [
            {"name": "http", "containerPort": 8000},
            {"name": "metrics", "containerPort": 8001},
        ]
    if ns == "lms":
        return c["name"] == ns and c.get("ports") == [{"containerPort": 8000}]
    if not wiki:
        return c["name"] == "front" and c.get("ports") == [{"name": "http", "containerPort": 8000}]
    return (
        c["name"] == "wiki"
        and c.get("ports") == [{"name": "http", "containerPort": 8080}]
        and [v for v in c["env"] if v["name"] == "WIKI_PUBLIC"]
        == [{"name": "WIKI_PUBLIC", "value": "true"}]
        and [v for v in c["env"] if v["name"] == "PUBLIC_ORIGIN"]
        == [{"name": "PUBLIC_ORIGIN", "value": "https://" + host}]
    )


def owner_render(*, owner=APP):
    ns = ROOTS[owner][0]
    release = owner
    path, file = (
        ("deploy/wiki-runtime/chart", "../values.yaml")
        if owner == "wiki-runtime"
        else (f"charts/{owner}", f"../../deploy/{owner}/values.yaml")
    )
    spec = yaml.safe_load((ROOT / f"deploy/argocd/apps/{release}.yaml").read_text())["spec"]
    src = spec["source"]
    files = [file, "alert-graphs.values.yaml"] if owner == "lms" else [file]
    params = src.get("helm", {}).get("parameters", [])
    reviewed_params = [[]]
    if owner in {"lms", "wishlist"}:
        reviewed_params.extend([[{"name": "publicWeb", "value": v}] for v in ("true", "false")])
    if (
        params not in reviewed_params
        or "sources" in spec
        or src
        != {
            "repoURL": "https://github.com/alchemmist/homelab.git",
            "targetRevision": "main",
            "path": path,
            "helm": {"releaseName": release, "valueFiles": files, "parameters": params},
        }
        or spec["destination"] != {"namespace": ns, "server": "https://kubernetes.default.svc"}
    ):
        raise ValueError("unreviewed owner release inputs")
    chart = ROOT / path
    command = ["helm", "template", release, str(chart), "-n", ns]
    for value_file in files:
        command.extend(["-f", str(chart / value_file)])
    for param in params:
        command.extend(["--set", param["name"] + "=" + param["value"]])
    raw = subprocess.check_output(command)
    return [d for d in yaml.safe_load_all(raw) if d]


def render():
    catalog = yaml.safe_load(CATALOG.read_text())
    bits = {
        k: eligible(owner_render(owner=w), catalog, owner=w)
        for k, w in [
            ("closedFormatQuorum", APP),
            ("closedWiki", "wiki-runtime"),
            ("closedMonori", "monori"),
            ("closedLms", "lms"),
            ("closedWishlist", "wishlist"),
        ]
    }
    bits.update(render_status(catalog))
    return "# Generated by python -m ci.quality.closed_root_owners\n" + yaml.safe_dump(bits)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    value = render()
    if args.check:
        return int(not OUTPUT.is_file() or OUTPUT.read_text() != value)
    OUTPUT.write_text(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
