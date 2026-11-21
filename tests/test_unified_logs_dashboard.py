"""Offline contracts: dashboard provisioning and native Loki queries, no credentials."""

import json
from pathlib import Path
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


class UnifiedLogsDashboardTest(unittest.TestCase):
    """Offline checks for the unified logs Grafana dashboard contract."""

    def setUp(self):
        self.dashboard = json.loads(
            (ROOT / "charts/monitoring-k3s/dashboards/logs.json").read_text()
        )

    def test_provisioning(self) -> None:
        """Require the logs dashboard label and its stable uid."""
        template = (ROOT / "charts/monitoring-k3s/templates/socrat-dashboard.yaml").read_text()
        assert '"logs"' in template
        assert 'grafana_dashboard: "1"' in template
        assert self.dashboard["uid"] == "socrat-unified-logs"

    def test_selectors_and_queries(self) -> None:
        """Require complete selectors, Loki queries, and top-aligned panels."""
        variables = self.dashboard["templating"]["list"]
        assert [v["name"] for v in variables] == ["service", "namespace", "node", "severity"]
        for variable in variables:
            assert variable["multi"]
            assert variable["allValue"] == (".+" if variable["name"] == "service" else ".*")
        for panel in self.dashboard["panels"]:
            assert panel["datasource"]["uid"] == "loki"
            expression = panel["targets"][0]["expr"]
            for name in ["service", "namespace", "node", "severity"]:
                assert "${" + name + ":regex}" in expression
            assert "| json" not in expression
        assert not any(p["type"] == "text" for p in self.dashboard["panels"])
        assert min(p["gridPos"]["y"] for p in self.dashboard["panels"]) == 0

    def test_explore_preserves_queries_and_time(self) -> None:
        """Require Explore links to keep the query and the dashboard time range."""
        url = self.dashboard["links"][0]["url"]
        state = json.loads(unquote(url.split("&left=", 1)[1]))
        assert state["range"] == {"from": "${__from}", "to": "${__to}"}
        assert state["queries"][0]["expr"] == self.dashboard["panels"][-1]["targets"][0]["expr"]
        assert state["datasource"] == "loki"


if __name__ == "__main__":
    unittest.main()
