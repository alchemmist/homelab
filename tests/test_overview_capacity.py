"""Overview keeps semicircular gauges; Traffic Light uses separate bar gauges."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAUGE_PERCENT_MAXIMUM = 100


class OverviewCapacityTest(unittest.TestCase):
    """Lock overview gauge options and independent traffic-light bar gauges."""

    def test_capacity_uses_original_native_gauge_options(self) -> None:
        """Require the original native gauge options on overview capacity panels."""
        dashboard = json.loads(
            (ROOT / "charts/monitoring-k3s/dashboards/overview.json").read_text()
        )
        assert dashboard["uid"] == "socrat-overview"
        panels = {p["id"]: p for p in dashboard["panels"]}
        for panel_id in (27, 28, 29):
            p = panels[panel_id]
            assert p["type"] == "gauge"
            assert p["options"] == {
                "reduceOptions": {"values": False, "calcs": ["lastNotNull"], "fields": ""},
                "orientation": "auto",
                "showThresholdLabels": False,
                "showThresholdMarkers": True,
                "text": {"titleSize": 12, "valueSize": 28},
            }
            assert p["fieldConfig"]["defaults"]["unit"] == "percent"
            assert p["fieldConfig"]["defaults"]["min"] == 0
            assert p["fieldConfig"]["defaults"]["max"] == GAUGE_PERCENT_MAXIMUM
            assert [t["refId"] for t in p["targets"]] == ["A", "B", "C"]
            assert [t["id"] for t in p["transformations"]] == [
                "joinByField",
                "organize",
                "filterByValue",
                "rowsToFields",
            ]

    def test_traffic_light_resource_bars_stay_independent(self) -> None:
        """Keep traffic-light resource panels as independent top-named bar gauges."""
        d = json.loads((ROOT / "charts/monitoring-k3s/dashboards/traffic-light.json").read_text())
        for p in d["panels"]:
            if p["id"] in (21, 22, 23):
                assert p["type"] == "bargauge"
                assert p["options"]["namePlacement"] == "top"


if __name__ == "__main__":
    unittest.main()
