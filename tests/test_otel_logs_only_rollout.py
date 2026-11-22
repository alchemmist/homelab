"""Log-only collector rollout preserves metrics state and refuses shared edits."""

import copy
import importlib.util
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("merge", ROOT / "ansible/scripts/otel-logs-only-config.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ScopedRolloutTests(unittest.TestCase):
    """Owned log exporters change without rewriting metrics, cursors, or endpoints."""

    def setUp(self) -> None:
        """Load the desired agent config and a live variant."""
        self.desired = yaml.safe_load((ROOT / "deploy/monitoring/otel/agent.yaml").read_text())
        self.live = copy.deepcopy(self.desired)
        self.live["service"]["pipelines"]["logs"]["exporters"] = ["otlp"]
        del self.live["exporters"]["otlp/logs"]

    def test_preserves_metrics_receivers_and_checkpoints(self) -> None:
        """Verify receiver cursors and metric pipelines stay on the live config."""
        self.live["receivers"]["filelog"]["start_at"] = "beginning"
        self.live["receivers"]["filelog"]["include"] = ["/original/path"]
        result = m.merge(self.live, self.desired)
        assert result["receivers"] == self.live["receivers"]
        assert result["extensions"] == self.live["extensions"]
        assert result["exporters"]["otlp"] == self.live["exporters"]["otlp"]
        assert (
            result["service"]["pipelines"]["metrics"]
            == self.live["service"]["pipelines"]["metrics"]
        )

    def test_only_known_broad_exclusion_is_narrowed(self) -> None:
        """Verify only the known broad self-log exclusion is replaced."""
        broad = "/var/log/pods/*_otel-*_*/*/*.log"
        self.live["receivers"]["filelog"]["exclude"] = [broad, "/custom/exclusion"]
        before = copy.deepcopy(self.live)
        result = m.merge(self.live, self.desired)
        expected = copy.deepcopy(before["receivers"])
        expected["filelog"]["exclude"] = self.desired["receivers"]["filelog"]["exclude"] + [
            "/custom/exclusion"
        ]
        assert result["receivers"] == expected
        assert self.live == before
        assert result["extensions"] == before["extensions"]

    def test_shared_mutation_refused(self) -> None:
        """Verify a shared memory limiter edit fails before the merge is accepted."""
        self.live["processors"]["memory_limiter"]["limit_mib"] = 987
        with self.assertRaises(ValueError):
            m.merge(self.live, self.desired)

    def test_existing_log_endpoint_is_authoritative(self) -> None:
        """Verify an existing live log endpoint is kept over the desired value."""
        self.live["exporters"]["otlp/logs"] = copy.deepcopy(self.desired["exporters"]["otlp/logs"])
        self.live["exporters"]["otlp/logs"]["endpoint"] = "existing:4317"
        assert (
            m.merge(self.live, self.desired)["exporters"]["otlp/logs"]["endpoint"]
            == "existing:4317"
        )

    def test_pinned_counter_names_and_ambiguity(self) -> None:
        """Verify one counter suffix is totaled and both suffixes together fail closed."""
        spec = importlib.util.spec_from_file_location(
            "gate", ROOT / "ansible/scripts/otel-logs-rollout-gate.py"
        )
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        record_gauge = {'otelcol_exporter_sent_log_records{exporter="otlp/logs"}': 12}
        expected_records = 12
        assert (
            gate.total(
                record_gauge,
                "otelcol_exporter_sent_log_records_total",
            )
            == expected_records
        )
        assert (
            gate.total(
                {"otelcol_exporter_sent_log_records_total": expected_records},
                "otelcol_exporter_sent_log_records_total",
            )
            == expected_records
        )
        with self.assertRaises(ValueError):
            gate.total(
                {
                    "otelcol_exporter_sent_log_records": 12,
                    "otelcol_exporter_sent_log_records_total": 12,
                },
                "otelcol_exporter_sent_log_records_total",
            )
