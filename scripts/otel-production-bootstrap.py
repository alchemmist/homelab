"""Provision stock cert-manager PKI and narrowly scoped host credential readers.

Requires the operator's explicit production/data-loss authorization. Does not
change scrape ownership, existing storage, routing, or datasource identities.
"""

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

NS = "cattle-monitoring-system"
LABELS = {"app.kubernetes.io/part-of": "homelab-otel"}
NODES = {
    "socrat-0": "10.250.0.1",
    "socrat-1": "10.250.0.3",
    "socrat-2": "10.250.0.2",
    "socrat-3": "10.250.0.5",
    "socrat-4": "10.250.0.40",
}


def _mapping(value: object) -> dict[str, object]:
    """Narrow one Kubernetes JSON response to a JSON object."""
    if isinstance(value, dict):
        return value
    message = "Kubernetes bootstrap did not return a JSON object"
    raise RuntimeError(message)


def kube(*args, document=None) -> object:
    result = subprocess.run(
        [
            "ssh",
            "-F",
            os.environ.get(
                "HOMELAB_OTEL_SSH_CONFIG", str(Path.home() / ".ssh/homelab-otel-migration.conf")
            ),
            "-o",
            "BatchMode=yes",
            "socrat-0",
            shlex.join(["kubectl", *args]),
        ],
        input=json.dumps(document) if document is not None else None,
        text=True,
        capture_output=True,
        timeout=90,
    )
    if result.returncode:
        raise RuntimeError("Kubernetes bootstrap operation failed; sensitive response omitted")
    # kubectl wait/delete emit human-readable output, not resource JSON.
    # Their exit status is checked above; never mistake a successful deletion
    # for a parser failure or retry it solely because its text was not JSON.
    command = args[2] if len(args) >= 3 and args[0] in ("-n", "--namespace") else args[0]
    if command in ("wait", "delete"):
        return None
    return json.loads(result.stdout) if result.stdout.strip() else None


def resource(kind, name, spec=None, api="cert-manager.io/v1") -> dict[str, object]:
    obj = {
        "apiVersion": api,
        "kind": kind,
        "metadata": {"name": name, "namespace": NS, "labels": LABELS},
    }
    if spec is not None:
        obj["spec"] = spec
    return obj


def resources(contract, api_server, pod) -> list[dict[str, object]]:
    out = [
        resource("Issuer", "otel-bootstrap-selfsigned", {"selfSigned": {}}),
        resource(
            "Certificate",
            "otel-root-ca",
            {
                "secretName": "otel-root-ca",
                "isCA": True,
                "commonName": "homelab-native-otel-ca",
                "duration": "87600h",
                "renewBefore": "8760h",
                "privateKey": {"algorithm": "ECDSA", "size": 256},
                "issuerRef": {"name": "otel-bootstrap-selfsigned", "kind": "Issuer"},
            },
        ),
        resource("Issuer", "otel-ca", {"ca": {"secretName": "otel-root-ca"}}),
    ]
    names = [(node, [ip], []) for node, ip in NODES.items()]
    names.append(
        ("cluster", [api_server, "127.0.0.1"], ["kube-prometheus-stack-prometheus." + NS + ".svc"])
    )
    for name, ips, dns in names:
        spec = {
            "secretName": "otel-tls-" + name,
            "commonName": "otel-" + name,
            "duration": "2160h",
            "renewBefore": "720h",
            "issuerRef": {"name": "otel-ca", "kind": "Issuer"},
            "privateKey": {"algorithm": "ECDSA", "size": 256, "rotationPolicy": "Always"},
            "usages": ["digital signature", "server auth", "client auth"],
            "ipAddresses": ips,
        }
        if dns:
            spec["dnsNames"] = dns
        out.append(resource("Certificate", "otel-tls-" + name, spec))
    for node in NODES:
        name = "otel-host-" + node
        out.append(resource("ServiceAccount", name, api="v1"))
        rules = [
            {
                "apiGroups": [""],
                "resources": ["secrets"],
                "resourceNames": ["otel-tls-" + node],
                "verbs": ["get"],
            },
            {
                "apiGroups": [""],
                "resources": ["serviceaccounts/token"],
                "resourceNames": [name],
                "verbs": ["create"],
            },
        ]
        if node == "socrat-0":
            rules.append(
                {
                    "apiGroups": [""],
                    "resources": ["secrets"],
                    "resourceNames": ["otel-source-auth"],
                    "verbs": ["get", "patch"],
                }
            )
        out.append(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "Role",
                "metadata": {"name": name, "namespace": NS, "labels": LABELS},
                "rules": rules,
            }
        )
        out.append(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {"name": name, "namespace": NS, "labels": LABELS},
                "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": name},
                "subjects": [{"kind": "ServiceAccount", "name": name, "namespace": NS}],
            }
        )
    for namespace in sorted({ref["namespace"] for ref in contract["requiredSecretKeys"]}):
        name = "otel-source-secret-reader"
        obj: dict[str, object] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "Role",
            "metadata": {"name": name, "namespace": namespace, "labels": LABELS},
            "rules": [
                {
                    "apiGroups": [""],
                    "resources": ["secrets"],
                    "resourceNames": sorted(
                        {
                            ref["secret"]
                            for ref in contract["requiredSecretKeys"]
                            if ref["namespace"] == namespace
                        }
                    ),
                    "verbs": ["get"],
                }
            ],
        }
        out.append(obj)
        out.append(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {"name": name, "namespace": namespace, "labels": LABELS},
                "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": name},
                "subjects": [
                    {"kind": "ServiceAccount", "name": "otel-host-socrat-0", "namespace": NS}
                ],
            }
        )
    return out


def run(bundle, output) -> None:
    os.umask(0o077)
    output.mkdir(mode=0o700, exist_ok=True)
    if (output / "bootstrap.json").exists():
        raise ValueError("Completed bootstrap exists; inspect before reissuing credentials")
    contract = json.loads((bundle / "contract.json").read_text())
    service = _mapping(
        kube("-n", NS, "get", "service", "kube-prometheus-stack-prometheus", "-o", "json")
    )
    pod = kube(
        "-n", NS, "get", "pod", "prometheus-kube-prometheus-stack-prometheus-0", "-o", "json"
    )
    objects = resources(contract, _mapping(service["spec"])["clusterIP"], pod)
    kube(
        "apply",
        "-f",
        "-",
        "-o",
        "json",
        document={"apiVersion": "v1", "kind": "List", "items": objects},
    )
    kube(
        "-n",
        NS,
        "wait",
        "--for=condition=Ready",
        "certificate",
        "-l",
        "app.kubernetes.io/part-of=homelab-otel",
        "--timeout=180s",
        "-o",
        "json",
    )
    refs = []
    mirrored = {}
    for index, reference in enumerate(contract["requiredSecretKeys"]):
        value = _mapping(
            _mapping(
                kube(
                    "-n", reference["namespace"], "get", "secret", reference["secret"], "-o", "json"
                )
            )["data"]
        )[reference["key"]]
        key = "source-" + str(index)
        mirrored[key] = value
        refs.append({**reference, "targetKey": key})
    mirror = resource("Secret", "otel-source-auth", api="v1")
    mirror.update(type="Opaque", data=mirrored)
    kube("apply", "-f", "-", "-o", "json", document=mirror)
    ca = _mapping(
        _mapping(kube("-n", NS, "get", "configmap", "kube-root-ca.crt", "-o", "json"))["data"]
    )["ca.crt"]
    if not isinstance(ca, str):
        message = "Kubernetes root CA certificate was not returned as a JSON string"
        raise TypeError(message)
    for node in NODES:
        directory = output / node
        directory.mkdir(mode=0o700)
        token = _mapping(
            kube("-n", NS, "create", "token", "otel-host-" + node, "--duration=24h", "-o", "json")
        )
        # kubectl -o json returns a TokenRequest with the expiration; only private files retain it.
        (directory / "token.json").write_text(json.dumps(token["status"]))
        (directory / "kubernetes-ca.crt").write_text(ca)
        (directory / "credentials.json").write_text(
            json.dumps(
                {
                    "namespace": NS,
                    "node": node,
                    "serviceAccount": "otel-host-" + node,
                    "apiServer": "https://10.250.0.1:6443",
                    "secret": "otel-tls-" + node,
                    "sourceReferences": refs if node == "socrat-0" else [],
                }
            )
        )
    (output / "contract.json").write_text(json.dumps(contract, indent=2))
    (output / "bootstrap.json").write_text(
        json.dumps(
            {
                "provisioned": True,
                "productionScrapeOwnershipChanged": False,
                "privateCAKeyDistributedToAgents": False,
                "hostCount": len(NODES),
                "prometheusServiceIP": _mapping(service["spec"])["clusterIP"],
            },
            indent=2,
        )
    )
    print(json.dumps({"provisioned": True, "scrapeOwnershipChanged": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.bundle, args.output)
