"""Check the external-chart evidence for the file provider's verified Argo HTTPS upstream."""

import argparse
import hashlib
from pathlib import Path

import yaml

from ci.quality import public_argocd_tls
from ci.quality.closed_root_backend import entries, view
from ci.quality.common import command
from ci.quality.public_web import CATALOG, ROOT

SHOW_ONLY = (
    "argocd-server/ingress",
    "argocd-server/service",
    "argocd-server/deployment",
    "extra-manifests",
)
KIND_ORDER = ("Ingress", "Service", "Deployment", "ServersTransport")
HOST = "argocd.socrat.alchemmist.xyz"
SERVER = "argo-cd-argocd-server"
TRANSPORT = "argocd-verified-tls"
SELECTOR = {"app.kubernetes.io/name": "argocd-server", "app.kubernetes.io/instance": "argo-cd"}
VALUES = ROOT / "deploy/platform/argo-cd/values.yaml"
# Together with the existing immutable chart digest, captures the exact inputs
# verified with --archive; an offline CI run cannot re-fetch the external chart.
VALUES_SHA256 = "54cd7c8e157592de729cc5568f6bf39fa00d8915be9b27667134fe131c9c40b9"
TRANSPORT_SPEC = {"serverName": HOST, "insecureSkipVerify": False}


def eligible(catalog: dict[str, object]) -> bool:
    """Accept only the reviewed Argo owner inputs and transport evidence."""
    try:
        owner = public_argocd_tls.owner()
    except (KeyError, ValueError, TypeError):
        return False
    hosts = view(view(catalog["hosts"]).get("argocd", {}))
    return (
        owner == ("argocd", HOST, "argocd-server-tls")
        and hosts.get(HOST) == {"dns": "managed", "tlsSourceName": "argocd-server-tls"}
        and hashlib.sha256(VALUES.read_bytes()).hexdigest() == VALUES_SHA256
        and yaml.safe_load((ROOT / "deploy/argocd/server-transport.yaml").read_text())
        == yaml.safe_load(VALUES.read_text())["extraObjects"][0]
    )


def verified_rows(
    ing: dict[str, object],
    svc: dict[str, object],
    deploy: dict[str, object],
    transport: dict[str, object],
) -> bool:
    """Check the exact owner render for the four verified upstream rows."""
    if not all(
        view(o["metadata"])["name"] == name
        and view(o["metadata"]).get("namespace", "argocd") == "argocd"
        and o["kind"] == kind
        for o, kind, name in (
            (ing, "Ingress", SERVER),
            (svc, "Service", SERVER),
            (deploy, "Deployment", SERVER),
            (transport, "ServersTransport", TRANSPORT),
        )
    ):
        return False
    server = view(view(deploy["spec"])["template"])
    pod = view(server["spec"])
    backend = {"service": {"name": SERVER, "port": {"number": 443}}}
    ing_meta = view(ing["metadata"])
    transport_spec = view(transport["spec"])
    return (
        view(ing["spec"])
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
        and view(ing_meta.get("labels", {})).get("homelab.alchemmist.xyz/public-web") == "true"
        and ing_meta.get("annotations") == {"cert-manager.io/cluster-issuer": "letsencrypt-http01"}
        and transport["apiVersion"] == "traefik.io/v1alpha1"
        and transport_spec == TRANSPORT_SPEC
        and transport_spec["insecureSkipVerify"] is False
        and view(svc["metadata"]).get("annotations")
        == {
            "traefik.ingress.kubernetes.io/service.serversscheme": "https",
            "traefik.ingress.kubernetes.io/service.serverstransport": (
                "argocd-argocd-verified-tls@kubernetescrd"
            ),
        }
        and view(svc["spec"])
        == {
            "type": "ClusterIP",
            "sessionAffinity": "None",
            "ports": [
                {"name": n, "protocol": "TCP", "port": p, "targetPort": 8080}
                for n, p in [("http", 80), ("https", 443)]
            ],
            "selector": SELECTOR,
        }
        and all(view(view(server["metadata"])["labels"]).get(k) == v for k, v in SELECTOR.items())
        and not pod.get("hostNetwork")
        and len(entries(pod["containers"])) == 1
        and view(entries(pod["containers"])[0])["name"] == "server"
        and view(entries(pod["containers"])[0])["ports"]
        == [
            {"name": "server", "containerPort": 8080, "protocol": "TCP"},
            {"name": "metrics", "containerPort": 8083, "protocol": "TCP"},
        ]
    )


def verify(archive: Path) -> None:
    """Validate the external --archive render against the reviewed contract."""
    public_argocd_tls.verify(archive)
    if not eligible(yaml.safe_load(CATALOG.read_text())):
        changed = "Argo owner or external render inputs changed"
        raise ValueError(changed)
    args = ["helm", "template", "argo-cd", str(archive), "-n", "argocd", "-f", str(VALUES)]
    for path in SHOW_ONLY:
        args += ["--show-only", "templates/" + path + ".yaml"]
    docs = [d for d in yaml.safe_load_all(command(args).stdout) if d]
    rows = {d["kind"]: d for d in docs}
    if len(docs) != len(SHOW_ONLY) or len(rows) != len(SHOW_ONLY):
        missing = "expected four distinct owner resources"
        raise ValueError(missing)
    if not verified_rows(*(rows[k] for k in KIND_ORDER)):
        wrong = "Argo verified upstream contract changed"
        raise ValueError(wrong)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    verify(parser.parse_args().archive)
