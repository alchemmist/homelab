"""Render a network-isolated Cats image-cache control, never a production release."""

import argparse
import re
import subprocess

import yaml

from ci.quality.public_web import CATALOG

PIN = "harbor.socrat.alchemmist.xyz/homelab/cats@sha256:af42b0edabcbbfa0541b6ee427ec8ba649ea7aa72429f7245f95c8dbfdb61a18"
NODES = ("socrat-0", "socrat-1", "socrat-3", "socrat-5")


def fixture(namespace):
    if not re.fullmatch(r"cats-cache-proof-[0-9]{10}", namespace):
        raise ValueError("disposable namespace required")
    root = CATALOG.parents[2]
    chart = root / "charts/cats"
    docs = [
        x
        for x in yaml.safe_load_all(
            subprocess.check_output(
                [
                    "helm",
                    "template",
                    "cats",
                    str(chart),
                    "-n",
                    namespace,
                    "-f",
                    str(root / "deploy/cats/values.yaml"),
                ]
            )
        )
        if x
    ]
    (sa,) = [x for x in docs if x["kind"] == "ServiceAccount"]
    (dep,) = [x for x in docs if x["kind"] == "Deployment"]
    spec = dep["spec"]["template"]["spec"]
    (container,) = spec["containers"]
    if (
        sa["metadata"] != {"name": "cats", "namespace": namespace}
        or sa.get("automountServiceAccountToken") is not False
        or spec.get("serviceAccountName") != "cats"
        or spec.get("automountServiceAccountToken") is not False
        or container["image"] != PIN
        or container["ports"] != [{"containerPort": 5173}]
        or set(container) != {"name", "image", "imagePullPolicy", "ports", "resources"}
        or container["imagePullPolicy"] != "IfNotPresent"
    ):
        raise ValueError("unreviewed Cats runtime")
    policy = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "no-network", "namespace": namespace},
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [],
            "egress": [],
        },
    }
    pods = [
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": node, "namespace": namespace},
            "spec": {
                "nodeSelector": {"kubernetes.io/hostname": node},
                "restartPolicy": "Never",
                "automountServiceAccountToken": False,
                "enableServiceLinks": False,
                "serviceAccountName": "cats",
                "containers": [{**container, "imagePullPolicy": "Never"}],
            },
        }
        for node in NODES
    ]
    return [policy, sa, *pods]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    ns = parser.parse_args().namespace
    print(yaml.safe_dump_all(fixture(ns)))


if __name__ == "__main__":
    main()
