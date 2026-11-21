"""Real Kubernetes API/controllers on disposable Kind nodes; never production."""

import importlib.util
import json
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from uuid import uuid4

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
NODE_IMAGE = (
    "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
)
NGINX_DIGEST = "sha256:b3c656d55d7ad751196f21b7fd2e8d4da9cb430e32f646adcf92441b72f82b14"


def run(argv, *, data=None, check=True, timeout=180):
    result = subprocess.run(
        argv, input=data, text=True, capture_output=True, check=False, timeout=timeout
    )
    if check and result.returncode:
        # Only synthetic fixture commands reach this helper; no operator secrets.
        raise RuntimeError(
            f"Ephemeral {argv[0]} failed ({result.returncode}): {result.stderr[-3000:]}"
        )
    return result


class Kube(Protocol):
    """Callable running `kubectl`, mirroring a types.SimpleNamespace-style wrapper."""

    def __call__(
        self, *args: str, data: str | None = None, check: bool = True, timeout: int = 180
    ) -> subprocess.CompletedProcess[str]:
        """Invoke kubectl with the given arguments."""
        ...


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    directory = tmp_path_factory.mktemp("kind-private")
    directory.chmod(0o700)
    config = directory / "kubeconfig"
    name = "homelab-qg-" + uuid4().hex[:12]
    context = "kind-" + name
    # An explicit file prevents Kind from merging/writing the operator's kubeconfig.
    try:
        run(
            [
                "kind",
                "create",
                "cluster",
                "--name",
                name,
                "--kubeconfig",
                str(config),
                "--image",
                NODE_IMAGE,
                "--wait",
                "120s",
            ],
            timeout=240,
        )
        config.chmod(0o600)

        def kube(*args, **kwargs):
            return run(
                [
                    "kubectl",
                    "--kubeconfig",
                    str(config),
                    "--context",
                    context,
                    "--request-timeout=30s",
                    *args,
                ],
                **kwargs,
            )

        view = json.loads(kube("config", "view", "-o", "json").stdout)
        assert view["current-context"] == context
        assert len(view["clusters"]) == 1
        assert urlparse(view["clusters"][0]["cluster"]["server"]).hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        version = json.loads(kube("version", "-o", "json").stdout)
        assert version["serverVersion"]["minor"].rstrip("+") == "36"
        yield name, config, context, kube
    finally:
        # Only this fixture's exact UUID-named cluster is ever removed.
        run(["kind", "delete", "cluster", "--name", name, "--kubeconfig", str(config)], timeout=120)


def test_release_reconciles_and_serves_http(cluster):
    _, config, context, kube = cluster
    ns = "chart-contract"
    kube("create", "namespace", ns)
    # Exercise the repository chart with an explicit public HTTP test workload.
    # This tests controller/service/rollout behavior, not the private Cats application.
    args = [
        "helm",
        "upgrade",
        "--install",
        "cats",
        str(ROOT / "charts/cats"),
        "--kubeconfig",
        str(config),
        "--kube-context",
        context,
        "-n",
        ns,
        "--set",
        "image.repository=nginx",
        "--set",
        "image.digest=" + NGINX_DIGEST,
        "--set",
        "service.targetPort=80",
        "--set-json",
        "imagePullSecrets=[]",
        "--wait",
        "--timeout",
        "180s",
    ]
    run(args, timeout=210)
    dep = json.loads(kube("-n", ns, "get", "deployment", "cats", "-o", "json").stdout)
    assert dep["status"]["availableReplicas"] == 2
    assert dep["status"]["observedGeneration"] == dep["metadata"]["generation"]
    body = kube("get", "--raw", f"/api/v1/namespaces/{ns}/services/cats:80/proxy/").stdout
    assert "Welcome to nginx!" in body
    run(args + ["--set", "replicaCount=3"], timeout=210)
    dep = json.loads(kube("-n", ns, "get", "deployment", "cats", "-o", "json").stdout)
    assert dep["status"]["availableReplicas"] == 3


def test_apiserver_rejects_invalid_rendered_replica_count(cluster):
    *_, kube = cluster
    rendered = run(
        ["helm", "template", "cats", str(ROOT / "charts/cats"), "--set", "replicaCount=-1"]
    ).stdout
    dep = next(d for d in yaml.safe_load_all(rendered) if d and d["kind"] == "Deployment")
    result = kube("apply", "--dry-run=server", "-f", "-", data=json.dumps(dep), check=False)
    assert result.returncode != 0
    assert "replicas" in result.stderr and "Invalid" in result.stderr


def test_application_reader_is_enforced_by_real_rbac(cluster):
    *_, kube = cluster
    spec = importlib.util.spec_from_file_location(
        "fixture_pki", ROOT / "scripts/otel-application-pki.py"
    )
    pki = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pki)
    kube("create", "namespace", pki.NS)
    objects = [d for d in pki.resources() if d["kind"] in {"ServiceAccount", "Role", "RoleBinding"}]
    kube(
        "apply", "-f", "-", data=json.dumps({"apiVersion": "v1", "kind": "List", "items": objects})
    )
    principal = f"system:serviceaccount:{pki.NS}:{pki.SA}"
    for verb, resource, allowed in [
        ("get", "secret/otel-app-tls-litellm", True),
        ("get", "secret/otel-root-ca", False),
        ("list", "secrets", False),
        ("update", "secret/otel-app-tls-litellm", False),
    ]:
        result = kube("--as", principal, "-n", pki.NS, "auth", "can-i", verb, resource, check=False)
        assert result.returncode in {0, 1}, result.stderr
        assert (result.stdout.strip() == "yes") is allowed
        assert result.returncode == (0 if allowed else 1)


def test_local_pv_retains_identity_after_claim_deletion(cluster):
    name, _, _, kube = cluster
    ns = "storage-contract"
    kube("create", "namespace", ns)
    run(["docker", "exec", name + "-control-plane", "mkdir", "-p", "/var/local/qg-retain"])
    pv = {
        "apiVersion": "v1",
        "kind": "PersistentVolume",
        "metadata": {"name": "qg-retain"},
        "spec": {
            "capacity": {"storage": "5Mi"},
            "accessModes": ["ReadWriteOnce"],
            "persistentVolumeReclaimPolicy": "Retain",
            "storageClassName": "",
            "local": {"path": "/var/local/qg-retain"},
            "nodeAffinity": {
                "required": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": [
                                {
                                    "key": "kubernetes.io/hostname",
                                    "operator": "In",
                                    "values": [name + "-control-plane"],
                                }
                            ]
                        }
                    ]
                }
            },
            "claimRef": {"namespace": ns, "name": "data"},
        },
    }
    pvc = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": "data", "namespace": ns},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "",
            "volumeName": "qg-retain",
            "resources": {"requests": {"storage": "5Mi"}},
        },
    }
    kube(
        "apply",
        "-f",
        "-",
        data=json.dumps({"apiVersion": "v1", "kind": "List", "items": [pv, pvc]}),
    )
    kube("-n", ns, "wait", "pvc/data", "--for=jsonpath={.status.phase}=Bound", "--timeout=45s")
    before = json.loads(kube("get", "pv", "qg-retain", "-o", "json").stdout)
    kube("-n", ns, "delete", "pvc", "data", "--wait=true")
    kube("wait", "pv/qg-retain", "--for=jsonpath={.status.phase}=Released", "--timeout=45s")
    after = json.loads(kube("get", "pv", "qg-retain", "-o", "json").stdout)
    assert before["metadata"]["uid"] == after["metadata"]["uid"]
    assert after["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
