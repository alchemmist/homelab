#!/usr/bin/env python3
"""Offline-only VPS relay renderer. No public DNS, runtime secret or apply action.

Separate transport failure domain from combined management on socrat-0.
TLS is terminated by existing trusted edge on socrat-2. No TURN/STUN/UDP listener,
no host network/capabilities, cluster token, local accounts or management API.
"""

import json
from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAME = "netbird-relay-vps"
NS = "identity"
HOST = "netbird-relay-vps.socrat.alchemmist.xyz"
URI = "rels://" + HOST + ":443"
HOME_URI = "rels://netbird.socrat.alchemmist.xyz:443"


def advertised_relays() -> dict[str, object]:
    # Native simplified schema: root relay YAML is intentionally ignored by 0.82.
    # Explicit endpoints suppress the combined relay; deploy both standalone pods.
    """Return the native simplified-schema relay advertisement configuration."""
    return {"addresses": [URI, HOME_URI], "credentialsTTL": "12h"}


def manifests() -> list[dict[str, object]]:
    """Render the pinned standalone relay Deployment and Service manifests."""
    image = json.loads((ROOT / "deploy/netbird/images.lock.json").read_text())["images"]["relay"]
    reference = image["repository"] + ":" + image["tag"] + "@" + image["digest"]
    labels = {"app": NAME}
    return [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": NAME, "namespace": NS},
            "spec": {
                "replicas": 1,
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "nodeSelector": {"kubernetes.io/hostname": "socrat-2"},
                        "automountServiceAccountToken": False,
                        "enableServiceLinks": False,
                        "containers": [
                            {
                                "name": "relay",
                                "image": reference,
                                "env": [
                                    {"name": k, "value": v}
                                    for k, v in {
                                        "NB_LISTEN_ADDRESS": ":33080",
                                        "NB_EXPOSED_ADDRESS": URI,
                                        "NB_HEALTH_LISTEN_ADDRESS": ":9000",
                                        "NB_METRICS_PORT": "9090",
                                        "NB_ENABLE_STUN": "false",
                                        "NB_LOG_LEVEL": "warn",
                                        "NB_LOG_FILE": "console",
                                    }.items()
                                ]
                                + [
                                    {
                                        "name": "NB_AUTH_SECRET",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": NAME + "-auth",
                                                "key": "auth-secret",
                                            }
                                        },
                                    }
                                ],
                                "ports": [{"name": "relay", "containerPort": 33080}],
                                "readinessProbe": {
                                    "httpGet": {"path": "/health", "port": 9000},
                                    "initialDelaySeconds": 2,
                                    "periodSeconds": 5,
                                },
                                "livenessProbe": {
                                    "tcpSocket": {"port": 9000},
                                    "initialDelaySeconds": 20,
                                },
                                "resources": {
                                    "requests": {"cpu": "5m", "memory": "16Mi"},
                                    "limits": {"cpu": "200m", "memory": "64Mi"},
                                },
                                "securityContext": {
                                    "runAsNonRoot": True,
                                    "runAsUser": 65532,
                                    "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]},
                                    "seccompProfile": {"type": "RuntimeDefault"},
                                },
                            }
                        ],
                    },
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": NAME,
                "namespace": NS,
                "annotations": {"traefik.ingress.kubernetes.io/service.nativelb": "true"},
            },
            # Native /health probes its own advertised public TLS endpoint. Publishing
            # this singleton before Ready via native ClusterIP LB breaks the circular
            # dependency. Traefik 3.7 filters EndpointSlice Serving, so PNRA alone is
            # insufficient. Relay HMAC authentication remains enforced for all clients.
            "spec": {
                "selector": labels,
                "publishNotReadyAddresses": True,
                "ports": [{"name": "relay", "port": 33080, "targetPort": "relay"}],
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": NAME, "namespace": NS},
            "spec": {
                "podSelector": {"matchLabels": labels},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [
                            {"ipBlock": {"cidr": ip + "/32"}}
                            for ip in ["109.120.141.60", "10.250.0.2", "10.42.0.0", "10.42.0.1"]
                        ],
                        "ports": [{"protocol": "TCP", "port": 33080}],
                    }
                ],
            },
        },
        {
            "apiVersion": "cert-manager.io/v1",
            "kind": "Certificate",
            "metadata": {"name": NAME + "-tls", "namespace": NS},
            "spec": {
                "secretName": NAME + "-tls",
                "dnsNames": [HOST],
                "issuerRef": {"name": "letsencrypt-http01", "kind": "ClusterIssuer"},
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": NAME,
                "namespace": NS,
                "annotations": {
                    "traefik.ingress.kubernetes.io/router.entrypoints": "websecure",
                    "traefik.ingress.kubernetes.io/router.priority": "200",
                },
            },
            "spec": {
                "ingressClassName": "traefik",
                "tls": [{"hosts": [HOST], "secretName": NAME + "-tls"}],
                "rules": [
                    {
                        "host": HOST,
                        "http": {
                            "paths": [
                                {
                                    "path": "/relay",
                                    "pathType": "Exact",
                                    "backend": {
                                        "service": {"name": NAME, "port": {"number": 33080}}
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
        },
    ]


def home_manifests() -> list[dict[str, object]]:
    """Separate home relay: external relays disable the combined v0.82 relay.

    Reuses the existing exact-host TLS certificate, never modifies its owner.
    Both existing home and VPS ingress controllers can reach this backend.
    """
    import copy

    docs = copy.deepcopy(manifests())
    name = "netbird-relay-home"
    labels = {"app": name}
    docs = [d for d in docs if d["kind"] != "Certificate"]
    for doc in docs:
        cast("dict[str, object]", doc["metadata"])["name"] = name
    deploy, service, policy, ingress = docs
    cast("dict[str, object]", cast("dict[str, object]", deploy["spec"])["selector"])[
        "matchLabels"
    ] = labels
    pod = cast("dict[str, object]", cast("dict[str, object]", deploy["spec"])["template"])
    cast("dict[str, object]", pod["metadata"])["labels"] = labels
    cast("dict[str, object]", pod["spec"])["nodeSelector"] = {"kubernetes.io/hostname": "socrat-0"}
    for env in cast(
        "list[dict[str, object]]",
        cast(
            "dict[str, object]",
            cast("list[object]", cast("dict[str, object]", pod["spec"])["containers"])[0],
        )["env"],
    ):
        if env["name"] == "NB_EXPOSED_ADDRESS":
            env["value"] = HOME_URI
        if env["name"] == "NB_AUTH_SECRET":
            cast("dict[str, object]", cast("dict[str, object]", env["valueFrom"])["secretKeyRef"])[
                "name"
            ] = name + "-auth"
    cast("dict[str, object]", service["spec"])["selector"] = labels
    policy_spec = cast("dict[str, object]", policy["spec"])
    cast("dict[str, object]", policy_spec["podSelector"])["matchLabels"] = labels
    cast("dict[str, object]", cast("list[object]", policy_spec["ingress"])[0])["from"] = [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
            "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}},
        }
    ] + [
        {"ipBlock": {"cidr": ip + "/32"}}
        for ip in [
            "109.120.141.60",
            "10.250.0.2",
            "10.42.0.0",
            "10.42.0.1",
            "192.168.0.23",
            "10.250.0.1",
            "10.42.2.1",
            "192.168.0.24",
            "10.250.0.3",
            "10.42.1.1",
        ]
    ]
    ingress_spec = cast("dict[str, object]", ingress["spec"])
    ingress_spec["tls"] = [
        {"hosts": ["netbird.socrat.alchemmist.xyz"], "secretName": "netbird-pilot-tls"}
    ]
    rules = cast("list[dict[str, object]]", ingress_spec["rules"])
    rules[0]["host"] = "netbird.socrat.alchemmist.xyz"
    http = cast("dict[str, object]", rules[0]["http"])
    paths = cast("list[dict[str, object]]", http["paths"])
    backend_service = cast(
        "dict[str, object]",
        cast("dict[str, object]", paths[0]["backend"])["service"],
    )
    backend_service["name"] = name
    return docs


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home", action="store_true", help="render bounded existing-home relay instead"
    )
    args = parser.parse_args()
    yaml.safe_dump_all(home_manifests() if args.home else manifests(), sys.stdout, sort_keys=False)
