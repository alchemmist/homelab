"""Contracts for the owner-approved four-app handoff; legacy volumes stay intact."""

import subprocess
import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]


class Metadata(TypedDict):
    """Kubernetes metadata section shared by rendered objects."""

    name: str
    annotations: dict[str, str]


class EnvVar(TypedDict, total=False):
    """One environment entry rendered into a container."""

    name: str
    value: str


class Container(TypedDict):
    """Workload container with its environment block."""

    name: str
    env: list[EnvVar]


class InitContainer(TypedDict):
    """Init container that gates the verified migration."""

    name: str
    args: list[str]
    volumeMounts: list[dict[str, object]]


class PodSpec(TypedDict):
    """Pod spec of a rendered workload deployment."""

    nodeSelector: dict[str, str]
    initContainers: list[InitContainer]
    containers: list[Container]
    automountServiceAccountToken: bool
    hostAliases: object
    volumes: list[dict[str, dict[str, object]]]


class Template(TypedDict):
    """Pod template inside a Deployment."""

    spec: PodSpec


class DeploymentSpec(TypedDict):
    """Deployment rollout fields exercised by these contracts."""

    replicas: int
    strategy: dict[str, str]
    template: Template


class DeploymentDoc(TypedDict):
    """A rendered Deployment manifest."""

    kind: str
    metadata: Metadata
    spec: DeploymentSpec


class ClaimSpec(TypedDict):
    """PersistentVolumeClaim fields checked by the storage contracts."""

    storageClassName: str
    volumeName: str


class ClaimDoc(TypedDict):
    """A rendered PersistentVolumeClaim manifest."""

    kind: str
    metadata: Metadata
    spec: ClaimSpec


class MatchExpression(TypedDict):
    """Node affinity match expression."""

    values: list[str]


class SelectorTerm(TypedDict):
    """Node selector term of a persistent volume."""

    matchExpressions: list[MatchExpression]


class NodeAffinityRequired(TypedDict):
    """Required node affinity block."""

    nodeSelectorTerms: list[SelectorTerm]


class NodeAffinity(TypedDict):
    """Node affinity of a persistent volume."""

    required: NodeAffinityRequired


class VolumeSpec(TypedDict):
    """PersistentVolume fields checked by the storage contracts."""

    persistentVolumeReclaimPolicy: str
    local: dict[str, str]
    nodeAffinity: NodeAffinity


class VolumeDoc(TypedDict):
    """A rendered PersistentVolume manifest."""

    kind: str
    metadata: Metadata
    spec: VolumeSpec


class ConfigMapDoc(TypedDict):
    """A rendered ConfigMap manifest."""

    kind: str
    metadata: Metadata
    data: dict[str, str]


class PolicySpec(TypedDict):
    """Isolation policy spec exercised by the terminal contract."""

    ingress: list[dict[str, object]]


class PolicyDoc(TypedDict):
    """A rendered NetworkPolicy manifest."""

    kind: str
    metadata: Metadata
    spec: PolicySpec


class ServiceDoc(TypedDict):
    """A rendered Service manifest."""

    kind: str
    metadata: Metadata
    spec: dict[str, str]


def render(name: str, *args: str) -> list[dict[str, object]]:
    """Render one chart offline and return its YAML documents."""
    return list(
        yaml.safe_load_all(
            subprocess.check_output(
                [
                    "helm",
                    "template",
                    name,
                    str(ROOT / "charts" / name),
                    "--namespace",
                    "llm" if name != "umami" else "umami",
                    *args,
                ],
                text=True,
            )
        )
    )


def obj(docs: Iterable[dict[str, object]], kind: str, name: str) -> dict[str, object]:
    """Return the first rendered document matching a kind and name."""
    return next(
        d
        for d in docs
        if d and d["kind"] == kind and cast("Metadata", d["metadata"])["name"] == name
    )


class FourAppMigrationTests(unittest.TestCase):
    """Offline contracts for the four-app vm105 placement handoff."""

    def test_stateless_placement_does_not_move_umami_database(self) -> None:
        """Move stateless apps while Umami's database stays on socrat-0."""
        for name in ["umami", "searxng"]:
            d = render(name)
            assert cast("DeploymentDoc", obj(d, "Deployment", name))["spec"]["template"]["spec"]["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
        db = cast("DeploymentDoc", obj(render("umami"), "Deployment", "umami-db"))["spec"][
            "template"
        ]["spec"]
        assert db["nodeSelector"] == {"kubernetes.io/hostname": "socrat-0"}
        assert db["volumes"][0]["hostPath"]["path"] == "/srv/umami/postgres"

    def test_dedicated_retained_vm_storage_and_original_claims(self) -> None:
        """Verify retained volumes and rebuilt claims for both UI apps."""
        for name in ["open-webui", "open-terminal"]:
            with self.subTest(app=name):
                docs = render(name)
                old = cast("ClaimDoc", obj(docs, "PersistentVolumeClaim", name + "-data"))
                assert old["spec"]["storageClassName"] == "local-path"
                assert old["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
                pv = cast("VolumeDoc", obj(docs, "PersistentVolume", name + "-socrat5"))
                assert pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
                assert pv["spec"]["local"]["path"] == "/mnt/files/homelab/" + name + "/data"
                assert pv["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"][0]["matchExpressions"][0]["values"] == ["socrat-5"]
                claim = cast("ClaimDoc", obj(docs, "PersistentVolumeClaim", name + "-socrat5"))
                assert claim["spec"]["volumeName"] == name + "-socrat5"
                assert claim["spec"]["storageClassName"] == ""

    def test_activation_requires_verified_existing_data_and_single_writer(self) -> None:
        """Require the verified-migration guard and a single writer per app."""
        for name, field in [
            ("open-webui", "persistence.claimName"),
            ("open-terminal", "claimName"),
        ]:
            with self.subTest(app=name):
                d = cast(
                    "DeploymentDoc",
                    obj(
                        render(
                            name,
                            "--set",
                            field + "=" + name + "-socrat5",
                            "--set",
                            "nodeName=socrat-5",
                        ),
                        "Deployment",
                        name,
                    ),
                )
                assert d["spec"]["replicas"] in [0, 1]
                assert d["spec"]["strategy"]["type"] == "Recreate"
                s = d["spec"]["template"]["spec"]
                assert s["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
                init = next(
                    c for c in s["initContainers"] if c["name"] == "require-verified-migration"
                )
                assert ".homelab-vm105-migration-verified.json" in init["args"][0]
                compile(init["args"][0], "<migration-guard>", "exec")
                assert init["volumeMounts"][0]["readOnly"]
                assert not s["automountServiceAccountToken"]

    def test_private_gateway_address_and_node_stay_together(self) -> None:
        """Keep the gateway on socrat-0 with its pinned listen address."""
        docs = render("open-webui", "--set", "nodeName=socrat-5")
        s = cast("DeploymentDoc", obj(docs, "Deployment", "open-webui-gateway"))["spec"][
            "template"
        ]["spec"]
        assert s["nodeSelector"] == {"kubernetes.io/hostname": "socrat-0"}
        cm = cast("ConfigMapDoc", obj(docs, "ConfigMap", "open-webui-gateway"))["data"][
            "default.conf"
        ]
        assert "listen 10.250.0.1:18080" in cm
        assert "return 308 https://$host$request_uri;" in cm

    def test_terminal_is_still_internal_and_webui_only(self) -> None:
        """Keep open-terminal reachable only from the open-webui pods."""
        docs = render("open-terminal")
        assert not any(d and d["kind"] == "Ingress" for d in docs)
        policy = cast("PolicyDoc", obj(docs, "NetworkPolicy", "open-terminal-isolation"))["spec"]
        assert policy["ingress"][0]["from"] == [{"podSelector": {"matchLabels": {"app": "open-webui"}}}]
        assert cast("ServiceDoc", obj(docs, "Service", "open-terminal"))["spec"]["type"] == "ClusterIP"

    def test_idp_internal_tls_route_is_scoped_to_webui_pod(self) -> None:
        """Route the Authentik TLS name only inside the open-webui pod."""
        docs = render("open-webui")
        spec = cast("DeploymentDoc", obj(docs, "Deployment", "open-webui"))["spec"]["template"][
            "spec"
        ]
        assert spec["hostAliases"] == [{"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}]
        assert "hostAliases" not in cast("DeploymentDoc", obj(docs, "Deployment", "open-webui-gateway"))["spec"]["template"]["spec"]
        env = {e["name"]: e for e in spec["containers"][0]["env"]}
        assert env["WEBUI_AUTH"]["value"] == "True"
        assert env["WEBUI_AUTH_COOKIE_SECURE"]["value"] == "True"
        assert "NODE_TLS_REJECT_UNAUTHORIZED" not in env
