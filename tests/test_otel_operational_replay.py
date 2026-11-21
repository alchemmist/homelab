"""Tests for OpenTelemetry operational replay handling."""

import base64
import copy
import importlib.util
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def module() -> ModuleType:
    """Test behavior for module."""
    spec = importlib.util.spec_from_file_location(
        "ops_replay", ROOT / "scripts/otel-operational-replay.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class OperationalReplayTests(unittest.TestCase):
    """Replay operational telemetry fixtures and check exact counts."""
    def test_exact_fixture_counts_cadence_and_unique_native_ids(self) -> None:
        """Exact fixture counts cadence and unique native ids."""

        helper = module()
        metrics, logs, traces, expected, ids = helper.fixtures(1793536000 * 10**9)
        assert len(expected) == 9
        assert all(b[0] - a[0] == 5 for a, b in zip(expected, expected[1:], strict=False))
        assert len(logs["resourceLogs"][0]["scopeLogs"][0]["logRecords"]) == 24
        assert len(helper.trace_records(traces)) == 9
        assert len(ids) == 9
        points = metrics["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["gauge"][
            "dataPoints"
        ]
        assert [int(p["timeUnixNano"]) // 10 ** 6 for p in points] == [int(p[0] * 1000) for p in expected]

    def test_matrix_requires_exact_values_timestamps_multiplicity_and_no_partial(self) -> None:
        """Matrix requires exact values timestamps multiplicity and no partial."""

        helper = module()
        expected = [[1, "0"], [6, "1"]]
        data = {
            "status": "success",
            "data": {"resultType": "matrix", "result": [{"values": expected}]},
        }
        assert helper.check_metrics(data, expected)
        for kind in ["extra-point", "extra-series", "timestamp", "warnings"]:
            changed = copy.deepcopy(data)
            if kind == "extra-point":
                changed["data"]["result"][0]["values"].append([7, "1"])
            if kind == "extra-series":
                changed["data"]["result"].append({"values": expected})
            if kind == "timestamp":
                changed["data"]["result"][0]["values"][1][0] = 7
            if kind == "warnings":
                changed["warnings"] = ["partial"]
            assert not helper.check_metrics(changed, expected)

    def test_rollback_candidate_changes_only_batch_timeout_preserving_queues_and_tls(self) -> None:
        """Rollback candidate changes only batch timeout preserving queues and tls."""

        import json

        original = {
            "processors": {"batch/metrics": {"timeout": "1s", "send_batch_size": 2}},
            "exporters": {
                "otlp_http/metrics": {
                    "tls": {"ca_file": "/isolated/ca.crt"},
                    "sending_queue": {"storage": "file_storage"},
                }
            },
        }
        encoded = json.dumps(original).encode()
        changed = json.loads(module().rollback_candidate(encoded))
        assert original["processors"]["batch/metrics"]["timeout"] == "1s"
        assert changed["processors"]["batch/metrics"]["timeout"] == "2s"
        changed["processors"]["batch/metrics"]["timeout"] = "1s"
        assert changed == original

    def test_native_trace_json_hex_and_base64(self) -> None:
        """Native trace json hex and base64."""

        helper = module()
        trace = "12" * 16
        for identity in [trace, base64.b64encode(bytes.fromhex(trace)).decode()]:
            assert helper.trace_records({"traceId": identity, "spanId": "34" * 8, "name": "fixture"}) == [(trace, "fixture")]
