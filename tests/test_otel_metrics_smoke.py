"""Offline checks for OTLP numeric-label comparison and dollar escaping."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "metrics_smoke", ROOT / "ansible/scripts/otel-metrics-smoke.py"
)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def series(bound, value="3") -> dict[tuple[tuple[str, object], ...], str]:
    """Test behavior for series."""
    return {
        tuple(sorted({"__name__": "smoke_duration_seconds_bucket", "le": bound}.items())): value
    }


class MetricsSmokeTests(unittest.TestCase):
    """Check histogram labels, duplicate series, and dollar escaping."""

    def test_native_otlp_numeric_label_normalization_is_accepted(self) -> None:
        """Accept equivalent numeric histogram bounds and reject changed values."""
        assert SMOKE.equivalent_series(series("1.0"), series("1"))
        assert SMOKE.equivalent_series(series("1e-05"), series("0.00001"))
        assert not SMOKE.equivalent_series(series("1.0", "2"), series("1", "3"))
        assert not SMOKE.equivalent_series(series("1.0"), series("2"))

    def test_semantic_view_never_merges_duplicate_series(self) -> None:
        """Reject a semantic view that would collapse two distinct series."""
        data = {**series("1.0"), **series("1")}
        with self.assertRaises(ValueError):
            SMOKE.equivalent_series(data, data)

    def test_ordinary_string_labels_are_not_normalized(self) -> None:
        """Keep ordinary string labels distinct when their text differs."""
        left = {(("__name__", "smoke_value"), ("le", "1.0")): "3"}
        right = {(("__name__", "smoke_value"), ("le", "1")): "3"}
        assert not SMOKE.equivalent_series(left, right)

    def test_summary_quantile_normalization_preserves_other_labels(self) -> None:
        """Normalize summary quantiles without dropping the other labels."""
        left = {(("__name__", "smoke_summary"), ("quantile", "1.0"), ("region", "one")): "3"}
        right = {(("__name__", "smoke_summary"), ("quantile", "1"), ("region", "one")): "3"}
        changed = {(("__name__", "smoke_summary"), ("quantile", "1"), ("region", "two")): "3"}
        assert SMOKE.equivalent_series(left, right)
        assert not SMOKE.equivalent_series(left, changed)

    def test_dollar_literals_survive_the_intended_one_pass_resolution(self) -> None:
        """Escape one dollar pass without treating the label as an env reference."""
        original = {
            "replacement": "$1",
            "regex": "(node)$",
            "labels": ["${env:NOT_AN_ENV_REFERENCE}"],
        }
        escaped = SMOKE.literal(original)
        assert escaped["replacement"] == "$$1"
        assert escaped["regex"] == "(node)$$"
        assert escaped["labels"] == ["$${env:NOT_AN_ENV_REFERENCE}"]

    def test_fixture_can_remove_a_series_without_stopping_the_target(self) -> None:
        """Drop the gauge series while the counter and summary lines remain."""
        assert "smoke_value" in SMOKE.metrics(17, True)
        removed = SMOKE.metrics(2, False)
        assert "smoke_value" not in removed
        assert "smoke_requests_total 2" in removed
        assert "smoke_summary_count 3" in removed
