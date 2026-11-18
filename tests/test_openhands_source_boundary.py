"""Render owner OpenHands values offline; never install or start the agent image."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from scripts.quality.common import command

ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "ghcr.io/openhands/agent-canvas:1.41.0@sha256:"
    "dcae97b63c9845fd1d4313857af6b10fb5888324a154238c4795ef86233d227c"
)


def _mapping(value: object) -> dict[str, object]:
    """Validate mapping keys without pretending to certify its dynamic fields."""
    assert isinstance(value, dict)
    result: dict[str, object] = {}
    for key, item in value.items():
        assert isinstance(key, str)
        result[key] = item
    return result


def _list(value: object) -> list[object]:
    """Retain every unknown element for subsequent concrete shape checks."""
    assert isinstance(value, list)
    return list(value)


def _one(documents: list[dict[str, object]], kind: str) -> dict[str, object]:
    """Require one resource of the requested kind rather than choosing an arbitrary one."""
    matches = [doc for doc in documents if doc.get("kind") == kind]
    assert len(matches) == 1
    return matches[0]


def _pod(documents: list[dict[str, object]]) -> dict[str, object]:
    """Read the concrete rendered pod template, not merely the override intentions."""
    stateful = _mapping(_one(documents, "StatefulSet")["spec"])
    return _mapping(_mapping(stateful["template"])["spec"])


def _assert_boundary(documents: list[dict[str, object]]) -> None:
    """Guard rendered privileges, storage and image without certifying runtime isolation."""
    allowed = {
        "Namespace",
        "ResourceQuota",
        "NetworkPolicy",
        "ServiceAccount",
        "Service",
        "StatefulSet",
    }
    for doc in documents:
        kind = doc.get("kind")
        assert isinstance(kind, str)
        assert kind in allowed, "Unexpected OpenHands resource kind"
    expected_count = 7
    assert len(documents) == expected_count
    pod = _pod(documents)
    assert pod["automountServiceAccountToken"] is False, "Pod token automount enabled"
    account = _one(documents, "ServiceAccount")
    assert account["automountServiceAccountToken"] is False, (
        "ServiceAccount token automount enabled"
    )
    assert not any(
        key in pod
        for key in ("volumes", "hostNetwork", "hostPID", "hostIPC", "initContainers")
    ), "Host or extra mounts/process namespaces enabled"
    security = _mapping(pod["securityContext"])
    assert security == {
        "fsGroup": 10001,
        "runAsGroup": 10001,
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    containers = _list(pod["containers"])
    assert len(containers) == 1
    container = _mapping(containers[0])
    assert container["image"] == IMAGE, "Image pin changed"
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
    }
    stateful = _mapping(_one(documents, "StatefulSet")["spec"])
    assert stateful["replicas"] == 1
    assert stateful["persistentVolumeClaimRetentionPolicy"] == {
        "whenDeleted": "Retain",
        "whenScaled": "Retain",
    }, "PVC retention weakened"
    claims = _list(stateful["volumeClaimTemplates"])
    assert len(claims) == 1
    claim = _mapping(claims[0])
    assert _mapping(claim["metadata"])["name"] == "data"
    spec = _mapping(claim["spec"])
    assert spec["storageClassName"] == "local-path"
    assert spec["accessModes"] == ["ReadWriteOnce"]
    assert _mapping(_mapping(spec["resources"])["requests"])["storage"] == "6Gi"
    assert container["volumeMounts"] == [
        {
            "name": "data",
            "mountPath": "/home/openhands/.openhands",
            "subPath": "openhands",
        },
        {
            "name": "data",
            "mountPath": "/home/openhands/workspace",
            "subPath": "workspace",
        },
    ]


@pytest.fixture(scope="module")
def rendered() -> list[dict[str, object]]:
    """Use only local Helm source/values with an explicitly empty kubeconfig."""
    result = command(
        [
            "helm",
            "template",
            "openhands",
            str(ROOT / "charts/openhands"),
            "-f",
            str(ROOT / "deploy/openhands/values.yaml"),
            "--namespace",
            "openhands",
            "--kubeconfig",
            "/dev/null",
        ]
    )
    return [
        _mapping(value)
        for value in yaml.safe_load_all(result.stdout)
        if value is not None
    ]


def test_owner_overrides_render_without_cluster_or_public_ingress_authority(
    rendered: list[dict[str, object]],
) -> None:
    """The deployed source graph keeps token/RBAC/ingress and PVC retention boundaries."""
    _assert_boundary(rendered)
    namespace = _mapping(_one(rendered, "Namespace")["metadata"])
    assert (
        _mapping(namespace["labels"])["pod-security.kubernetes.io/enforce"]
        == "restricted"
    )
    policy = _mapping(_one(rendered, "NetworkPolicy")["spec"])
    assert policy["policyTypes"] == ["Ingress", "Egress"]


@pytest.mark.parametrize(
    ("violation", "message"),
    [
        ("pod-token", "Pod token automount enabled"),
        ("sa-token", "ServiceAccount token automount enabled"),
        ("host-volume", "Host or extra mounts"),
        ("image", "Image pin changed"),
        ("retention", "PVC retention weakened"),
        ("rbac", "Unexpected OpenHands resource kind"),
        ("ingress", "Unexpected OpenHands resource kind"),
    ],
)
def test_boundary_rejects_real_rendered_graph_mutations(
    rendered: list[dict[str, object]],
    violation: str,
    message: str,
) -> None:
    """Each critical synthetic violation must fail the same compiled-graph guard."""
    documents = copy.deepcopy(rendered)
    pod = _pod(documents)
    # Helpers copy mappings, so explicitly replace the relevant source resource.
    stateful = _one(documents, "StatefulSet")
    spec = _mapping(stateful["spec"])
    template = _mapping(spec["template"])
    if violation == "pod-token":
        pod["automountServiceAccountToken"] = True
    elif violation == "sa-token":
        _one(documents, "ServiceAccount")["automountServiceAccountToken"] = True
    elif violation == "host-volume":
        pod["volumes"] = [{"name": "host", "hostPath": {"path": "/"}}]
    elif violation == "image":
        containers = _list(pod["containers"])
        container = _mapping(containers[0])
        container["image"] = "unverified:latest"
        containers[0] = container
        pod["containers"] = containers
    elif violation == "retention":
        spec["persistentVolumeClaimRetentionPolicy"] = {
            "whenDeleted": "Delete",
            "whenScaled": "Delete",
        }
    elif violation == "rbac":
        documents.append({"kind": "ClusterRoleBinding"})
    elif violation == "ingress":
        documents.append({"kind": "Ingress"})
    else:
        raise AssertionError(violation)
    template["spec"] = pod
    spec["template"] = template
    stateful["spec"] = spec
    with pytest.raises(AssertionError, match=message):
        _assert_boundary(documents)
