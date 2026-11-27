"""Check the external-chart evidence for the file provider's verified Argo HTTPS upstream."""

import argparse
import hashlib
import subprocess
from pathlib import Path

import yaml

from ci.quality import public_argocd_tls
from ci.quality.public_web import CATALOG, ROOT

HOST = "argocd.socrat.alchemmist.xyz"
SERVER = "argo-cd-argocd-server"
TRANSPORT = "argocd-verified-tls"
SELECTOR = {"app.kubernetes.io/name": "argocd-server", "app.kubernetes.io/instance": "argo-cd"}
VALUES = ROOT / "deploy/platform/argo-cd/values.yaml"
# Together with the existing immutable chart digest, captures the exact inputs
# verified with --archive; an offline CI run cannot re-fetch the external chart.
VALUES_SHA256 = "54cd7c8e157592de729cc5568f6bf39fa00d8915be9b27667134fe131c9c40b9"
TRANSPORT_SPEC = {"serverName": HOST, "insecureSkipVerify": False}


def eligible(catalog):
    try:
        owner = public_argocd_tls.owner()
    except (KeyError, ValueError, TypeError):
        return False
    return (
        owner == ("argocd", HOST, "argocd-server-tls")
        and catalog["hosts"].get("argocd", {}).get(HOST)
        == {"dns": "managed", "tlsSourceName": "argocd-server-tls"}
        and hashlib.sha256(VALUES.read_bytes()).hexdigest() == VALUES_SHA256
        and yaml.safe_load((ROOT / "deploy/argocd/server-transport.yaml").read_text())
        == yaml.safe_load(VALUES.read_text())["extraObjects"][0]
    )


def verified_rows(ing, svc, deploy, transport):
    if not all(
        o["metadata"]["name"] == name
        and o["metadata"].get("namespace", "argocd") == "argocd"
        and o["kind"] == kind
        for o, kind, name in (
            (ing, "Ingress", SERVER),
            (svc, "Service", SERVER),
            (deploy, "Deployment", SERVER),
            (transport, "ServersTransport", TRANSPORT),
        )
    ):
        return False
    server = deploy["spec"]["template"]
    pod = server["spec"]
    backend = {"service": {"name": SERVER, "port": {"number": 443}}}
    return (
        ing["spec"]
        == {
            "ingressClassName": "traefik",
            "tls": [{"hosts": [HOST], "secretName": "argocd-server-tls"}],
            "rules": [
                {
                    "host": HOST,
                    "http": {"paths": [{"path": "/", "pathType": "Prefix", "backend": backend}]},
                }
            ],
        }
        and ing["metadata"].get("labels", {}).get("homelab.alchemmist.xyz/public-web") == "true"
        and ing["metadata"].get("annotations")
        == {"cert-manager.io/cluster-issuer": "letsencrypt-http01"}
        and transport["apiVersion"] == "traefik.io/v1alpha1"
        and transport["spec"] == TRANSPORT_SPEC
        and transport["spec"]["insecureSkipVerify"] is False
        and svc["metadata"].get("annotations")
        == {
            "traefik.ingress.kubernetes.io/service.serversscheme": "https",
            "traefik.ingress.kubernetes.io/service.serverstransport": "argocd-argocd-verified-tls@kubernetescrd",
        }
        and svc["spec"]
        == {
            "type": "ClusterIP",
            "sessionAffinity": "None",
            "ports": [
                {"name": n, "protocol": "TCP", "port": p, "targetPort": 8080}
                for n, p in [("http", 80), ("https", 443)]
            ],
            "selector": SELECTOR,
        }
        and all(server["metadata"]["labels"].get(k) == v for k, v in SELECTOR.items())
        and not pod.get("hostNetwork")
        and len(pod["containers"]) == 1
        and pod["containers"][0]["name"] == "server"
        and pod["containers"][0]["ports"]
        == [
            {"name": "server", "containerPort": 8080, "protocol": "TCP"},
            {"name": "metrics", "containerPort": 8083, "protocol": "TCP"},
        ]
    )


def verify(archive):
    public_argocd_tls.verify(archive)
    if not eligible(yaml.safe_load(CATALOG.read_text())):
        raise ValueError("Argo owner or external render inputs changed")
    args = ["helm", "template", "argo-cd", str(archive), "-n", "argocd", "-f", str(VALUES)]
    for path in (
        "argocd-server/ingress",
        "argocd-server/service",
        "argocd-server/deployment",
        "extra-manifests",
    ):
        args += ["--show-only", "templates/" + path + ".yaml"]
    docs = [d for d in yaml.safe_load_all(subprocess.check_output(args)) if d]
    rows = {d["kind"]: d for d in docs}
    if len(docs) != 4 or len(rows) != 4:
        raise ValueError("expected four distinct owner resources")
    if not verified_rows(
        *(rows[k] for k in ("Ingress", "Service", "Deployment", "ServersTransport"))
    ):
        raise ValueError("Argo verified upstream contract changed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    verify(parser.parse_args().archive)
