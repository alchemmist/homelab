import copy
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import TypedDict, cast
import unittest
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
    def fixture(self) -> tuple[_Deployment, list[_Pod]]:
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
        d, p = self.fixture()
        self.assertTrue(placement.converged(d, p, "socrat-5"))

    def test_replica_zero_never_passes(self) -> None:
        d, _ = self.fixture()
        d["spec"]["replicas"] = 0
        self.assertFalse(placement.converged(d, [], "socrat-5"))

    def test_old_ready_pod_never_passes(self) -> None:
        d, p = self.fixture()
        p[0]["spec"]["nodeName"] = "socrat-1"
        self.assertFalse(placement.converged(d, p, "socrat-5"))

    def test_missing_status_and_old_generation_never_pass(self) -> None:
        d, p = self.fixture()
        p[0]["status"]["containerStatuses"] = []
        self.assertFalse(placement.converged(d, p, "socrat-5"))
        d, p = self.fixture()
        d["status"]["observedGeneration"] = 1
        self.assertFalse(placement.converged(d, p, "socrat-5"))

    def test_terminating_or_extra_writer_never_passes(self) -> None:
        d, p = self.fixture()
        self.assertFalse(placement.converged(d, p + copy.deepcopy(p), "socrat-5"))
        p[0]["metadata"]["deletionTimestamp"] = "2026-11-16T00:00:00Z"
        self.assertFalse(placement.converged(d, p, "socrat-5"))


class CurrentDocumentation(unittest.TestCase):
    def test_current_wiki_storage_matches_canonical_values(self) -> None:
        claim = yaml.safe_load((ROOT / "deploy/wiki-runtime/values.yaml").read_text())[
            "persistence"
        ]["existingClaim"]
        for name in ["wiki/README.md", "docs/wiki.md"]:
            self.assertIn("`" + claim + "`", (ROOT / name).read_text())

    def test_current_context_is_bounded_and_history_separate(self) -> None:
        text = (ROOT / "llm-wiki/context.md").read_text()
        self.assertLess(len(text.splitlines()), 160)
        self.assertIn("context-history-20261116.md", text)
        self.assertTrue((ROOT / "llm-wiki/context-history-20261116.md").is_file())


class GrafanaStorage(unittest.TestCase):
    def test_explicit_existing_data_and_retained_claims(self) -> None:
        v = yaml.safe_load((ROOT / "charts/grafana/values.yaml").read_text())["grafana"]
        self.assertEqual(v["nodeSelector"]["kubernetes.io/hostname"], "socrat-5")
        self.assertEqual(v["persistence"]["existingClaim"], "grafana-socrat5")
        o = yaml.safe_load((ROOT / "deploy/grafana/values.yaml").read_text())["grafana"]
        self.assertEqual(o["replicas"], 1)
        guard = o["extraInitContainers"][0]
        self.assertIn("test -s /var/lib/grafana/grafana.db", guard["command"])
        self.assertTrue(guard["volumeMounts"][0]["readOnly"])
        self.assertTrue(guard["securityContext"]["runAsNonRoot"])
        docs = list(
            yaml.safe_load_all((ROOT / "deploy/storage/grafana-socrat5/volume.yaml").read_text())
        )
        pv = next(d for d in docs if d["kind"] == "PersistentVolume")
        self.assertEqual(pv["spec"]["persistentVolumeReclaimPolicy"], "Retain")
        self.assertEqual(pv["spec"]["local"]["path"], "/mnt/files/homelab/grafana/data")
        claims = [d for d in docs if d["kind"] == "PersistentVolumeClaim"]
        self.assertEqual(
            {d["metadata"]["name"] for d in claims},
            {"kube-prometheus-stack-grafana", "grafana-socrat5"},
        )
        for d in claims:
            self.assertEqual(
                d["metadata"]["annotations"]["argocd.argoproj.io/sync-options"],
                "Prune=false,Delete=false",
            )

    def test_mcp_remains_read_only_stateless_and_exact_version(self) -> None:
        v = yaml.safe_load((ROOT / "charts/grafana-mcp/values.yaml").read_text())
        self.assertEqual(v["nodeSelector"]["kubernetes.io/hostname"], "socrat-5")
        self.assertEqual(v["image"]["tag"], "2.0.2")
        self.assertEqual(v["credentialsSecret"], "grafana-mcp-credentials")


if __name__ == "__main__":
    unittest.main()
