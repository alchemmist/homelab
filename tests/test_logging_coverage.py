"""Check logging coverage classification without inventory or query clients."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "coverage_check",
    Path(__file__).resolve().parents[1] / "scripts/logging-coverage.py",
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class CoverageTests(unittest.TestCase):
    """Classify inventory and metadata fixtures without contacting a cluster."""

    def test_inventory_includes_all_container_types_and_empty_controllers(self) -> None:
        """Count every container type and keep an empty controller in the inventory."""
        pod = {
            "metadata": {"namespace": "ns", "name": "pod"},
            "spec": {
                k: [{"name": k}] for k in ("containers", "initContainers", "ephemeralContainers")
            },
        }
        sources = M.inventory(
            {"items": [pod]},
            {
                "items": [
                    {
                        "kind": "Deployment",
                        "metadata": {"namespace": "ns", "name": "zero"},
                    }
                ]
            },
            [],
        )
        expected_sources = 4
        assert len(sources) == expected_sources
        assert M.assess(sources, [], [])[-1]["status"] == "exists"
        assert M.assess(sources, [], [])[0]["status"] == "unknown"

    def test_delivery_is_distinct_from_canonical_labels_and_silence(self) -> None:
        """Separate raw emission, canonical labels, missing points, and expected silence."""
        source = {
            "kind": "host",
            "host": "node",
            "unit": "k3s.service",
            "exists": True,
            "emission": "expected",
        }
        labels = {"host_name": "node", "service_name": "k3s.service"}
        point = {"labels": labels, "count": 1}
        assert M.assess([source], [point], [point])[0]["status"] == "emits"
        labels["severity"] = "unknown"
        assert M.assess([source], [point], [point])[0]["status"] == "verified"
        assert M.assess([source], [], [point])[0]["status"] == "unknown"
        source["emission"] = "silent"
        assert M.assess([source], [], [])[0]["status"] == "silent"

    def test_mixed_contract_is_not_verified(self) -> None:
        """Keep a source at emits when only some fresh points carry the contract."""
        source = {"kind": "host", "host": "n", "unit": "u"}
        points = [
            {"labels": {"host_name": "n", "service_name": "u", **extra}, "count": 1}
            for extra in ({}, {"severity": "info"})
        ]
        assert M.assess([source], points, points)[0]["status"] == "emits"

    def test_bounds_and_metadata_validation(self) -> None:
        """Build bounded queries and reject partial or unsafe metadata documents."""
        for window in (600, 3600):
            query = M.query('{host_name!=""}', window)
            assert "count_over_time" in query
            assert "[" + str(window) + "s]" in query
        for point in (
            {"metric": {"body": "secret"}, "value": [0, "1"]},
            {"metric": {}, "value": [0, "NaN"]},
        ):
            with self.assertRaises(ValueError):
                M.validate(
                    {
                        "status": "success",
                        "data": {"resultType": "vector", "result": [point]},
                    }
                )
        with self.assertRaises(ValueError):
            M.validate(
                {
                    "status": "success",
                    "warnings": ["partial"],
                    "data": {"resultType": "vector", "result": []},
                }
            )

    def test_structured_host_unit_and_zero_counts(self) -> None:
        """Require a positive count before a structured host unit is verified."""
        source = {"kind": "host", "host": "n", "unit": "u"}
        point = {
            "labels": {
                "host_name": "n",
                "audit_unit": "u",
                "service_name": "app",
                "severity": "warn",
            },
            "count": 0,
        }
        assert M.assess([source], [point], [point])[0]["status"] == "unknown"
        point["count"] = 2
        assert M.assess([source], [point], [point])[0]["status"] == "verified"

    def test_kubernetes_requires_host_and_all_source_identities(self) -> None:
        """Drop canonical verification when any required Kubernetes identity is absent."""
        source = {
            "kind": "container",
            "namespace": "ns",
            "pod": "pod",
            "container": "app",
        }
        labels = {
            "host_name": "node",
            "k8s_namespace_name": "ns",
            "audit_pod": "pod",
            "audit_container": "app",
            "service_name": "svc",
            "severity": "info",
        }
        good = {"labels": labels, "count": 1}
        assert M.assess([source], [good], [good])[0]["status"] == "verified"
        for key in labels:
            with self.subTest(missing=key):
                incomplete = {
                    "labels": {k: v for k, v in labels.items() if k != key},
                    "count": 1,
                }
                assert not M.canonical_identity(source, incomplete["labels"])
                row = M.assess([source], [incomplete], [incomplete])[0]
                assert row["status"] != "verified"
                assert not row["canonical"]
        incomplete = {
            "labels": {k: v for k, v in labels.items() if k != "host_name"},
            "count": 1,
        }
        row = M.assess([source], [good, incomplete], [good, incomplete])[0]
        assert row["status"] == "emits"
        assert not row["canonical"]
        assert row["legacyObserved"]

    def test_host_inventory_does_not_infer_emission_from_installed_or_running(
        self,
    ) -> None:
        """Record systemd units as present without treating service state as emission."""
        snapshots = [
            {
                "host": "node",
                "services": {
                    "running.service": {
                        "source": "systemd",
                        "state": "running",
                        "status": "enabled",
                    },
                    "idle.service": {
                        "source": "systemd",
                        "state": "stopped",
                        "status": "disabled",
                    },
                    "oneshot.service": {
                        "source": "systemd",
                        "state": "stopped",
                        "status": "enabled",
                    },
                    "other": {"source": "sysv", "state": "running"},
                },
            }
        ]
        registry = M.host_registry(snapshots)
        expected_registered = 3
        assert len(registry) == expected_registered
        assert all(r["exists"] is True and r["emission"] == "unknown" for r in registry)
        rows = M.assess(M.inventory({}, {}, registry), [], [])
        assert all(r["status"] == "unknown" and r["emits"] is None for r in rows)
        with self.assertRaises(ValueError):
            M.host_registry(snapshots + snapshots)

    def test_host_canonical_requires_matching_host_and_unit(self) -> None:
        """Accept a host identity only when every required label still matches."""
        source = {"kind": "host", "host": "node", "unit": "unit.service"}
        labels = {
            "host_name": "node",
            "audit_unit": "unit.service",
            "service_name": "app",
            "severity": "info",
        }
        assert M.canonical_identity(source, labels)
        for key in labels:
            assert not M.canonical_identity(source, {k: v for k, v in labels.items() if k != key})
