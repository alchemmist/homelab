"""Current rollout ownership and readiness are required, not merely matching labels."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict
from unittest.mock import patch

import yaml


class _DeploymentMetadata(TypedDict):
    """Immutable deployment identity and its observed rollout generation."""

    uid: str
    generation: int
    annotations: dict[str, str]


class _DeploymentSpec(TypedDict):
    """Single-replica workload selector used by the offline fixture."""

    replicas: int
    selector: dict[str, dict[str, str]]


class _Deployment(TypedDict):
    """Rollout counters stay mutable for unavailable and extra-replica mutations."""

    metadata: _DeploymentMetadata
    spec: _DeploymentSpec
    status: dict[str, int]


class _ReplicaMetadata(TypedDict):
    """Current ReplicaSet UID, revision and deployment controller reference."""

    uid: str
    ownerReferences: list[dict[str, str | bool]]
    annotations: dict[str, str]


class _ReplicaSet(TypedDict):
    """Minimal ReplicaSet carrying the current-revision ownership chain."""

    metadata: _ReplicaMetadata


class _PodMetadata(TypedDict):
    """Pod ownership remains mutable to exercise invalid controller references."""

    ownerReferences: list[dict[str, str | bool]]


class _PodSpec(TypedDict):
    """Expected node and containers, without running a workload."""

    nodeName: str
    containers: list[dict[str, str]]


class _PodStatus(TypedDict):
    """Pod phase and readiness are separate conditions in the placement contract."""

    phase: str
    conditions: list[dict[str, str]]
    containerStatuses: list[dict[str, str | bool]]


class _Pod(TypedDict):
    """Ready local pod fixture, never a production API object."""

    metadata: _PodMetadata
    spec: _PodSpec
    status: _PodStatus


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("target", ROOT / "ansible/scripts/check_target_placement.py")
assert spec is not None
assert spec.loader is not None
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


def owner(kind: str, uid: str) -> dict[str, str | bool]:
    """Build a controller reference with an explicit kind and immutable UID."""
    return {"kind": kind, "uid": uid, "controller": True}


def fixture() -> tuple[_Deployment, list[_ReplicaSet], list[_Pod]]:
    """Build a ready deployment and its current ReplicaSet-owned pod."""
    d: _Deployment = {
        "metadata": {
            "uid": "deployment",
            "generation": 2,
            "annotations": {"deployment.kubernetes.io/revision": "3"},
        },
        "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "fixture"}}},
        "status": {
            "replicas": 1,
            "updatedReplicas": 1,
            "readyReplicas": 1,
            "availableReplicas": 1,
            "observedGeneration": 2,
        },
    }
    r: _ReplicaSet = {
        "metadata": {
            "uid": "rs-current",
            "ownerReferences": [owner("Deployment", "deployment")],
            "annotations": {"deployment.kubernetes.io/revision": "3"},
        }
    }
    p: _Pod = {
        "metadata": {"ownerReferences": [owner("ReplicaSet", "rs-current")]},
        "spec": {"nodeName": "socrat-5", "containers": [{"name": "app"}]},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "app", "ready": True}],
        },
    }
    return d, [r], [p]


class Ownership(unittest.TestCase):
    """Reject old revisions, invalid controller references and incomplete rollout readiness."""

    def test_current_revision_and_ready_pod(self) -> None:
        """Verify current revision and ready pod."""
        d, r, p = fixture()
        assert target.converged(d, p, "socrat-5")
        assert target.owned_by_current_revision(d, r, p)

    def test_old_revision_rejected_even_with_valid_deployment_owner(self) -> None:
        """Verify old revision rejected even with valid deployment owner."""
        d, r, p = fixture()
        r[0]["metadata"]["annotations"]["deployment.kubernetes.io/revision"] = "2"
        assert not target.owned_by_current_revision(d, r, p)

    def test_wrong_owner_uid_kind_or_noncontroller_rejected(self) -> None:
        """Verify wrong owner uid kind or noncontroller rejected."""
        mutations: tuple[tuple[str, str | bool], ...] = (
            ("uid", "wrong"),
            ("kind", "wrong"),
            ("controller", False),
        )
        for level in ["replicaset", "pod"]:
            for field, value in mutations:
                with self.subTest(level=level, field=field):
                    d, r, p = fixture()
                    obj = r[0] if level == "replicaset" else p[0]
                    obj["metadata"]["ownerReferences"][0][field] = value
                    assert not target.owned_by_current_revision(d, r, p)

    def test_missing_revision_and_empty_pods_do_not_pass_vacuously(self) -> None:
        """Verify missing revision and empty pods do not pass vacuously."""
        d, r, p = fixture()
        assert not target.owned_by_current_revision(d, r, [])
        d["metadata"]["annotations"].clear()
        assert not target.owned_by_current_revision(d, r, p)

    def test_readiness_gate_or_nonrunning_phase_rejected(self) -> None:
        """Verify readiness gate or nonrunning phase rejected."""
        d, _r, p = fixture()
        p[0]["status"]["conditions"][0]["status"] = "False"
        assert not target.converged(d, p, "socrat-5")
        d, _r, p = fixture()
        p[0]["status"]["phase"] = "Pending"
        assert not target.converged(d, p, "socrat-5")

    def test_unavailable_or_extra_deployment_replicas_rejected(self) -> None:
        """Verify unavailable or extra deployment replicas rejected."""
        for field, value in [
            ("availableReplicas", 0),
            ("replicas", 2),
            ("unavailableReplicas", 1),
        ]:
            with self.subTest(field=field):
                d, _r, p = fixture()
                d["status"][field] = value
                assert not target.converged(d, p, "socrat-5")


class Transport(unittest.TestCase):
    """Exercise mocked read-only CLI transport and its shared Ansible checker contract."""

    def test_cli_transports_only_get_requests_and_uses_same_contract(self) -> None:
        """Verify cli transports only get requests and uses same contract."""
        for local in [False, True]:
            with self.subTest(local=local):
                d, r, p = fixture()
                results = [
                    SimpleNamespace(returncode=0, stdout=json.dumps(obj))
                    for obj in [d, {"items": p}, {"items": r}]
                ]
                argv = [
                    "check_target_placement.py",
                    "--namespace",
                    "fixture",
                    "--deployment",
                    "fixture",
                    "--node",
                    "socrat-5",
                    "--timeout",
                    "1",
                ] + (["--local"] if local else [])
                with (
                    patch("sys.argv", argv),
                    patch.object(target.subprocess, "run", side_effect=results) as run,
                ):
                    target.main()
                placement_gets = 3
                assert run.call_count == placement_gets
                for call in run.call_args_list:
                    command = call.args[0]
                    if local:
                        assert command[0] == "kubectl"
                        assert "get" in command
                    else:
                        assert command[0] == "ssh"
                        assert " get " in command[-1]

    def test_ansible_uses_same_checker_without_nested_ssh(self) -> None:
        """Verify ansible uses same checker without nested ssh."""
        tasks = yaml.safe_load(
            (ROOT / "ansible/roles/rancher_placement/tasks/verify.yml").read_text()
        )
        assert "ansible.builtin.assert" in tasks[0]
        script = tasks[1]["ansible.builtin.script"]
        assert "../../scripts/check_target_placement.py" in script["cmd"]
        assert "--local" in script["cmd"]
        assert script["executable"] == "/usr/bin/python3"
        assert not tasks[1]["changed_when"]


if __name__ == "__main__":
    unittest.main()
