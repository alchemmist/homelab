"""Offline contracts for isolated OpenTelemetry signal fixtures."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "signals_smoke", ROOT / "ansible/scripts/otel-signals-smoke.py"
)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class SignalSmokeTests(unittest.TestCase):
    """Sampling, duration, and log-timestamp contracts for synthetic signals."""

    def test_trace_fixtures_cover_sampling_categories_with_unique_ids(self) -> None:
        """Require 232 unique traces and the fixed category counts."""
        body, groups = SMOKE.trace_fixtures(10**18)
        spans = body["resourceSpans"][0]["scopeSpans"][0]["spans"]
        expected_spans = 232
        assert len(spans) == expected_spans
        assert len({span["traceId"] for span in spans}) == expected_spans
        assert {key: len(value) for key, value in groups.items()} == {
            "error": 8,
            "http5xx": 8,
            "legacy5xx": 8,
            "slow": 8,
            "normal": 200,
        }
        error_status_code = 2
        expected_error_spans = 8
        assert (
            sum(span["status"]["code"] == error_status_code for span in spans)
            == expected_error_spans
        )

    def test_slow_trace_duration_exceeds_the_native_sampling_threshold(self) -> None:
        """Require slow traces to last three seconds and the rest one tenth."""
        body, groups = SMOKE.trace_fixtures(10**18)
        for span in body["resourceSpans"][0]["scopeSpans"][0]["spans"]:
            duration = int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])
            assert duration == (3000000000 if span["traceId"] in groups["slow"] else 100000000)

    def test_logs_include_separate_zero_historical_and_fresh_cases(self) -> None:
        """Require fresh, zero, and one-hour-old log timestamps in that order."""
        now = 10**18
        records = SMOKE.logs_fixture(now)["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        assert [int(record["timeUnixNano"]) for record in records] == [
            now,
            0,
            now - 3600 * 10**9,
        ]
        assert SMOKE.SECRET in records[0]["body"]["stringValue"]
        assert SMOKE.SERVICE.startswith("otel-isolated-")
