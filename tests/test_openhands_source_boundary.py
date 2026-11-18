"""Render owner OpenHands values offline; never install or start the agent image."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

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
        key in pod for key in ("volumes", "hostNetwork", "hostPID", "hostIPC", "initContainers")
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
    return [_mapping(value) for value in yaml.safe_load_all(result.stdout) if value is not None]


def test_owner_overrides_render_without_cluster_or_public_ingress_authority(
    rendered: list[dict[str, object]],
) -> None:
    """The deployed source graph keeps token/RBAC/ingress and PVC retention boundaries."""
    _assert_boundary(rendered)
    namespace = _mapping(_one(rendered, "Namespace")["metadata"])
    assert _mapping(namespace["labels"])["pod-security.kubernetes.io/enforce"] == "restricted"
    policy = _mapping(_one(rendered, "NetworkPolicy")["spec"])
    assert policy["policyTypes"] == ["Ingress", "Egress"]


def test_openhands_mcp_inventory_is_explicitly_no_client() -> None:
    """Do not confuse source admission with a new diagnostics/agent authorization."""
    audit = _mapping(json.loads((ROOT / "deploy/mcp/service-audit.json").read_text()))
    rows = [_mapping(value) for value in _list(audit["applications"])]
    matches = [row for row in rows if row.get("application") == "openhands"]
    assert len(matches) == 1
    assert matches[0]["decision"] == "no-client"
    assert "connector" not in matches[0]
    config = _mapping(json.loads((ROOT / ".pi/mcp.json").read_text()))
    assert "openhands" not in _mapping(config["mcpServers"])


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


@pytest.fixture
def handoff_gate(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load reviewed read-only definitions with the sole native fetch transport trapped."""

    def denied(*_args: object, **_kwargs: object) -> None:
        message = "Native fetch transport forbidden"
        raise AssertionError(message)

    monkeypatch.setattr(subprocess, "check_output", denied)
    spec = importlib.util.spec_from_file_location(
        "reviewed_openhands_gate",
        ROOT / "scripts/openhands-pr-ready.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert isinstance(module, ModuleType)
    return module


def _handoff_snapshot() -> dict[str, object]:
    """Construct only synthetic GitHub shapes, without authentication or API access."""
    head = "a" * 40
    return {
        "url": "https://github.com/example/example/pull/1",
        "headRefOid": head,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "commits": {"nodes": [{"commit": {"oid": head}}]},
        "reviews": {
            "nodes": [
                {
                    "id": "review",
                    "author": {"login": "review-bot", "__typename": "Bot"},
                    "state": "APPROVED",
                    "body": "",
                    "commit": {"oid": head},
                }
            ]
        },
        "comments": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "statusCheckRollup": {
            "contexts": {
                "nodes": [
                    {
                        "__typename": "CheckRun",
                        "name": "tests",
                        "status": "COMPLETED",
                        "conclusion": "SUCCESS",
                    },
                ]
            }
        },
    }


@pytest.mark.parametrize("kind", ["UnknownContext", None, ""])
def test_handoff_rejects_unknown_ci_variants(handoff_gate: ModuleType, kind: object) -> None:
    """An arbitrary state=SUCCESS must not impersonate a legacy StatusContext."""
    snapshot = _handoff_snapshot()
    snapshot["statusCheckRollup"] = {
        "contexts": {"nodes": [{"__typename": kind, "state": "SUCCESS"}]}
    }
    report = _mapping(handoff_gate.assess(snapshot, {"review-bot"}, {"publisher"}))
    assert report["ready_to_review"] is False
    assert any(str(item).startswith("CI not green:") for item in _list(report["blockers"]))


@pytest.mark.parametrize("head", [None, "", "a" * 39, "g" * 40])
def test_handoff_rejects_invalid_head_identity(handoff_gate: ModuleType, head: object) -> None:
    """Matching malformed review identity cannot certify a concrete current commit."""
    snapshot = _handoff_snapshot()
    snapshot["headRefOid"] = head
    snapshot["reviews"] = {
        "nodes": [
            {
                "id": "review",
                "author": {"login": "review-bot", "__typename": "Bot"},
                "state": "APPROVED",
                "body": "",
                "commit": {"oid": head},
            }
        ]
    }
    report = _mapping(handoff_gate.assess(snapshot, {"review-bot"}, {"publisher"}))
    assert report["ready_to_review"] is False
    assert "Missing or invalid current head identity" in _list(report["blockers"])


@pytest.mark.parametrize("kind", ["CheckRun", "StatusContext"])
def test_handoff_retains_both_native_ci_success_variants(
    handoff_gate: ModuleType, kind: str
) -> None:
    """Actual check-run and legacy status contexts retain original positive behavior."""
    snapshot = _handoff_snapshot()
    snapshot["statusCheckRollup"] = {
        "contexts": {
            "nodes": [
                {
                    "__typename": kind,
                    "state": "SUCCESS",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                },
            ]
        }
    }
    report = _mapping(handoff_gate.assess(snapshot, {"review-bot"}, {"publisher"}))
    assert report["ready_to_review"] is True
