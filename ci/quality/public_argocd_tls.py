"""Recheck the one external Helm chart's reviewed TLS pin from a local archive."""

import argparse
import hashlib
import subprocess
from pathlib import Path

import yaml

from ci.quality.public_web import CATALOG, ROOT

ARCHIVE_SHA256 = "d8f096d87513b41ff754053a7f9604c943bf29c15436a79226fd51595ea67d05"
VERSION = "10.11.6"


def owner() -> tuple[str, str, str]:
    """Bind the captured render to the declared chart version and input values."""
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/argo-cd.yaml").read_text())
    src, values = app["spec"]["sources"]
    ns = app["spec"]["destination"]["namespace"]
    if (
        src
        != {
            "repoURL": "https://argoproj.github.io/argo-helm",
            "chart": "argo-cd",
            "targetRevision": VERSION,
            "helm": {"valueFiles": ["$values/deploy/platform/argo-cd/values.yaml"]},
        }
        or values
        != {
            "repoURL": "https://github.com/alchemmist/homelab.git",
            "targetRevision": "main",
            "ref": "values",
        }
        or ns != "argocd"
        or app["metadata"]["name"] != "argo-cd"
    ):
        raise ValueError("Argo CD release requires a new upstream render review")
    ingress = yaml.safe_load((ROOT / "deploy/platform/argo-cd/values.yaml").read_text())["server"][
        "ingress"
    ]
    host = ingress["hostname"]
    if (
        ingress["enabled"] is not True
        or ingress["tls"] is not True
        or ingress["ingressClassName"] != "traefik"
        or ingress["annotations"].get("cert-manager.io/cluster-issuer") != "letsencrypt-http01"
    ):
        raise ValueError("unexpected Argo CD ingress settings")
    return ns, host, "argocd-server-tls"


def verify(path: Path) -> None:
    with path.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != ARCHIVE_SHA256:
            raise ValueError("unreviewed Argo CD chart archive")
    ns, host, key = owner()
    rendered = subprocess.check_output(
        [
            "helm",
            "template",
            "argo-cd",
            str(path),
            "-n",
            ns,
            "-f",
            str(ROOT / "deploy/platform/argo-cd/values.yaml"),
            "--show-only",
            "templates/argocd-server/ingress.yaml",
        ],
        text=True,
    )
    (ing,) = yaml.safe_load_all(rendered)
    spec = ing["spec"]
    meta = ing["metadata"]
    if (
        ing["kind"] != "Ingress"
        or meta.get("namespace", ns) != ns
        or spec["ingressClassName"] != "traefik"
        or meta["annotations"].get("cert-manager.io/cluster-issuer") != "letsencrypt-http01"
        or [r["host"] for r in spec["rules"]] != [host]
        or spec["tls"] != [{"hosts": [host], "secretName": key}]
        or yaml.safe_load(CATALOG.read_text())["hosts"][ns][host].get("tlsSourceName") != key
    ):
        raise ValueError("Argo CD TLS pin and upstream render differ")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    verify(parser.parse_args().archive)
    print("Verified external Argo CD chart and TLS source reference.")
