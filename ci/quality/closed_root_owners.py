"""Compile narrowly reviewed root HTTP admissions from the owner's complete Argo render."""

import argparse
import subprocess

import yaml

from ci.quality.public_web import CATALOG, ROOT

APP = "format-quorum"
HOST = "fq.alchemmist.xyz"
PIN = "format-quorum-tls"
OUTPUT = ROOT / "deploy/public-web/closed-root-owners.yaml"


def eligible(items, catalog, *, wiki=False):
    """Only translate the complete reviewed root matcher and exact upstream contract."""
    ns, name, host, pin = (
        ("wiki", "wiki-runtime-wiki", "wiki.socrat.alchemmist.xyz", "wiki-tls")
        if wiki
        else (APP, APP, HOST, PIN)
    )
    selector = {
        "app.kubernetes.io/name": "hugo-docs-wiki" if wiki else APP,
        "app.kubernetes.io/instance": "wiki-runtime" if wiki else APP,
    }
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
    if wiki and not _wiki_runtime(items, ns, name, selector, host):
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
                    "port": 8080 if wiki else 80,
                    "targetPort": "http" if wiki else 3000,
                }
            ],
        }
    )


def _wiki_runtime(items, ns, name, selector, host):
    workloads = [
        d
        for d in items
        if d["kind"] == "Deployment"
        and d["metadata"].get("namespace", ns) == ns
        and d["metadata"]["name"] == name
    ]
    if len(workloads) != 1:
        return False
    template = workloads[0]["spec"]["template"]
    pod = template["spec"]
    containers = pod["containers"]
    if template["metadata"]["labels"] != selector or pod.get("hostNetwork") or len(containers) != 1:
        return False
    c = containers[0]
    return (
        c["name"] == "wiki"
        and c.get("ports") == [{"name": "http", "containerPort": 8080}]
        and [v for v in c["env"] if v["name"] == "WIKI_PUBLIC"]
        == [{"name": "WIKI_PUBLIC", "value": "true"}]
        and [v for v in c["env"] if v["name"] == "PUBLIC_ORIGIN"]
        == [{"name": "PUBLIC_ORIGIN", "value": "https://" + host}]
    )


def owner_render(*, wiki=False):
    release, path, file, ns = (
        ("wiki-runtime", "deploy/wiki-runtime/chart", "../values.yaml", "wiki")
        if wiki
        else (APP, "charts/format-quorum", "../../deploy/format-quorum/values.yaml", APP)
    )
    spec = yaml.safe_load((ROOT / f"deploy/argocd/apps/{release}.yaml").read_text())["spec"]
    src = spec["source"]
    if (
        "sources" in spec
        or src
        != {
            "repoURL": "https://github.com/alchemmist/homelab.git",
            "targetRevision": "main",
            "path": path,
            "helm": {"releaseName": release, "valueFiles": [file], "parameters": []},
        }
        or spec["destination"] != {"namespace": ns, "server": "https://kubernetes.default.svc"}
    ):
        raise ValueError("unreviewed owner release inputs")
    chart = ROOT / path
    raw = subprocess.check_output(
        ["helm", "template", release, str(chart), "-n", ns, "-f", str(chart / file)]
    )
    return [d for d in yaml.safe_load_all(raw) if d]


def render():
    catalog = yaml.safe_load(CATALOG.read_text())
    bits = {
        k: eligible(owner_render(wiki=w), catalog, wiki=w)
        for k, w in [("closedFormatQuorum", False), ("closedWiki", True)]
    }
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
