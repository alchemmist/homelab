"""Dashboard descriptions preserve query, alert timing and unrelated display settings."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import NotRequired, TypedDict

import pytest


class _Defaults(TypedDict):
    """Display properties that must survive the known milliseconds correction."""

    unit: str
    min: int


class _FieldConfig(TypedDict):
    """Grafana default display configuration, separate from the query targets."""

    defaults: _Defaults


class _Panel(TypedDict):
    """Rows, query panels and text panels supply different optional properties."""

    id: int
    type: str
    panels: NotRequired[list[_Panel]]
    targets: NotRequired[list[dict[str, str]]]
    description: NotRequired[str]
    fieldConfig: NotRequired[_FieldConfig]


class _Dashboard(TypedDict):
    """Local mutable dashboard fixture; no Grafana API is contacted."""

    uid: str
    panels: list[_Panel]


# Functional syntax preserves Prometheus's reserved Python keyword "for".
_AlertRule = TypedDict(
    "_AlertRule",
    {"alert": str, "expr": str, "for": str, "annotations": dict[str, str]},
)


SOURCE = Path(__file__).resolve().parents[1] / "ansible/files/dashboard_descriptions.py"
SPEC = importlib.util.spec_from_file_location("dashboard_descriptions", SOURCE)
assert SPEC is not None
assert SPEC.loader is not None
DESCRIPTIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DESCRIPTIONS)


class DashboardDescriptionsTest(unittest.TestCase):
    """Description enrichment cannot silently alter the owning alert or query."""

    def test_pending_readiness_description_uses_the_actual_confirmation_period(
        self,
    ) -> None:
        """Readiness text reflects the actual pending interval, not a stale duration."""
        rule: _AlertRule = {
            "alert": "KubePodNotReady",
            "expr": "example > 0",
            "for": "5m",
            "annotations": {
                "description": "Already unready for 15 minutes.",
                "rancher_url": "https://example.test/pod",
            },
        }
        resource = {"kind": "PrometheusRule", "spec": {"groups": [{"rules": [rule]}]}}
        DESCRIPTIONS.apply_alert_descriptions(resource)
        assert "becomes Firing after 5m" in rule["annotations"]["description"]
        assert "15 minutes" not in rule["annotations"]["description"]
        assert rule["annotations"]["rancher_url"] == "https://example.test/pod"
        assert rule["expr"] == "example > 0"
        assert rule["for"] == "5m"

    def test_nested_panels_get_descriptions_without_changing_queries(self) -> None:
        """Nested panels get descriptions while targets and text panels stay untouched."""
        target = {"expr": 'up{job="example"}'}
        dashboard: _Dashboard = {
            "uid": "example",
            "panels": [
                {
                    "id": 1,
                    "type": "row",
                    "panels": [
                        {"id": 2, "type": "timeseries", "targets": [target]},
                    ],
                },
                {"id": 3, "type": "text"},
            ],
        }
        DESCRIPTIONS.apply_descriptions(
            dashboard, {"example": {"2": "Whether the service can be scraped."}}
        )
        panel = dashboard["panels"][0]["panels"][0]
        assert panel["description"] == "Whether the service can be scraped."
        assert panel["targets"] == [target]
        assert "description" not in dashboard["panels"][1]

    def test_new_panel_without_description_blocks_rendering(self) -> None:
        """Unmapped query panels fail with the exact dashboard and panel identity."""
        dashboard: _Dashboard = {
            "uid": "example",
            "panels": [{"id": 2, "type": "stat"}],
        }
        with pytest.raises(ValueError, match="example, panel 2"):
            DESCRIPTIONS.apply_descriptions(dashboard, {"example": {}})

    def test_known_unit_correction_keeps_other_display_settings(self) -> None:
        """The known unit correction preserves the independently configured minimum."""
        dashboard: _Dashboard = {
            "uid": "6be0s85Mk",
            "panels": [
                {
                    "id": 4,
                    "type": "timeseries",
                    "fieldConfig": {"defaults": {"unit": "ms", "min": 0}},
                },
            ],
        }
        DESCRIPTIONS.apply_descriptions(
            dashboard, {"6be0s85Mk": {"4": "HTTP request duration in seconds."}}
        )
        assert dashboard["panels"][0]["fieldConfig"]["defaults"] == {
            "unit": "s",
            "min": 0,
        }


if __name__ == "__main__":
    unittest.main()
