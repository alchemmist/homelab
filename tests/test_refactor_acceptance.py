"""Acceptance tests for the public entry refactor."""

import copy
import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from typing import TypedDict, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]


def module(name: str, path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


placement = module("placement", "scripts/check_target_placement.py")


class _PodSpec(TypedDict):
    """Pod fields that placement convergence judges."""

    nodeName: str
    containers: list[dict[str, object]]


class _DeploymentStatus(TypedDict):
    """Deployment status fields used by convergence checks."""

    observedGeneration: int
    updatedReplicas: int
    readyReplicas: int
    replicas: int
    availableReplicas: int


class _Deployment(TypedDict):
    """Deployment fields used by convergence checks."""

    metadata: dict[str, int]
    spec: dict[str, int]
    status: _DeploymentStatus


class _PodStatus(TypedDict):
    """Pod runtime state used by the readiness predicates."""

    phase: str
    conditions: list[dict[str, str]]
    containerStatuses: list[dict[str, object]]


class _Pod(TypedDict):
    """Mutable pod fixture consumed by the placement checks."""

    metadata: dict[str, str]
    spec: _PodSpec
    status: _PodStatus


class Convergence(unittest.TestCase):
    """Check refactor acceptance fixtures converge to expected state."""
    def fixture(self) -> tuple[_Deployment, list[_Pod]]:
        """Return a fixture document for convergence tests."""

        d = {
            "metadata": {"generation": 2},
            "spec": {"replicas": 1},
            "status": {
                "observedGeneration": 2,
                "updatedReplicas": 1,
                "readyReplicas": 1,
                "replicas": 1,
                "availableReplicas": 1,
            },
        }
        p: _Pod = {
            "metadata": {},
            "spec": {"nodeName": "socrat-5", "containers": [{"name": "grafana"}]},
            "status": {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [{"name": "grafana", "ready": True}],
            },
        }
        return cast(_Deployment, d), [p]

    def test_ready_desired_node(self) -> None:
        """Ready desired node."""

        d, p = self.fixture()
        assert placement.converged(d, p, "socrat-5")

    def test_replica_zero_never_passes(self) -> None:
        """Replica zero never passes."""

        d, _ = self.fixture()
        d["spec"]["replicas"] = 0
        assert not placement.converged(d, [], "socrat-5")

    def test_old_ready_pod_never_passes(self) -> None:
        """Old ready pod never passes."""

        d, p = self.fixture()
        p[0]["spec"]["nodeName"] = "socrat-1"
        assert not placement.converged(d, p, "socrat-5")

    def test_missing_status_and_old_generation_never_pass(self) -> None:
        """Missing status and old generation never pass."""

        d, p = self.fixture()
        p[0]["status"]["containerStatuses"] = []
        assert not placement.converged(d, p, "socrat-5")
        d, p = self.fixture()
        d["status"]["observedGeneration"] = 1
        assert not placement.converged(d, p, "socrat-5")

    def test_terminating_or_extra_writer_never_passes(self) -> None:
        """Terminating or extra writer never passes."""

        d, p = self.fixture()
        assert not placement.converged(d, p + copy.deepcopy(p), "socrat-5")
        p[0]["metadata"]["deletionTimestamp"] = "2026-11-16T00:00:00Z"
        assert not placement.converged(d, p, "socrat-5")


class CurrentDocumentation(unittest.TestCase):
    """Verify current wiki documentation matches canonical values."""
    def test_current_wiki_storage_matches_canonical_values(self) -> None:
        """Current wiki storage matches canonical values."""

        claim = yaml.safe_load((ROOT / "deploy/wiki-runtime/values.yaml").read_text())[
            "persistence"
        ]["existingClaim"]
        for name in ["wiki/README.md", "docs/wiki.md"]:
            assert "`" + claim + "`" in (ROOT / name).read_text()

    def test_current_context_is_bounded_and_history_separate(self) -> None:
        """Current context is bounded and history separate."""

        text = (ROOT / "llm-wiki/context.md").read_text()
        context_line_budget = 160
        assert len(text.splitlines()) < context_line_budget
        assert "context-history-20261116.md" in text
        assert (ROOT / "llm-wiki/context-history-20261116.md").is_file()


class GrafanaStorage(unittest.TestCase):
    """Check Grafana storage keeps existing data and retained claims."""
    def test_explicit_existing_data_and_retained_claims(self) -> None:
        """Explicit existing data and retained claims."""

        v = yaml.safe_load((ROOT / "charts/grafana/values.yaml").read_text())["grafana"]
        assert v["nodeSelector"]["kubernetes.io/hostname"] == "socrat-5"
        assert v["persistence"]["existingClaim"] == "grafana-socrat5"
        o = yaml.safe_load((ROOT / "deploy/grafana/values.yaml").read_text())["grafana"]
        assert o["replicas"] == 1
        guard = o["extraInitContainers"][0]
        assert "test -s /var/lib/grafana/grafana.db" in guard["command"]
        assert guard["volumeMounts"][0]["readOnly"]
        assert guard["securityContext"]["runAsNonRoot"]
        docs = list(
            yaml.safe_load_all((ROOT / "deploy/storage/grafana-socrat5/volume.yaml").read_text())
        )
        pv = next(d for d in docs if d["kind"] == "PersistentVolume")
        assert pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
        assert pv["spec"]["local"]["path"] == "/mnt/files/homelab/grafana/data"
        claims = [d for d in docs if d["kind"] == "PersistentVolumeClaim"]
        assert {d["metadata"]["name"] for d in claims} == {
            "kube-prometheus-stack-grafana",
            "grafana-socrat5",
        }
        for d in claims:
            assert (
                d["metadata"]["annotations"]["argocd.argoproj.io/sync-options"]
                == "Prune=false,Delete=false"
            )

    def test_mcp_remains_read_only_stateless_and_exact_version(self) -> None:
        """Mcp remains read only stateless and exact version."""

        v = yaml.safe_load((ROOT / "charts/grafana-mcp/values.yaml").read_text())
        assert v["nodeSelector"]["kubernetes.io/hostname"] == "socrat-5"
        assert v["image"]["tag"] == "2.0.2"
        assert v["credentialsSecret"] == "grafana-mcp-credentials"


if __name__ == "__main__":
    unittest.main()
