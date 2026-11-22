"""Offline full rule coverage and condition-preservation regression."""

import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path

import yaml

from ci.quality.common import command

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alert_graphs", ROOT / "scripts/alert_graphs.py")
assert spec is not None
assert spec.loader is not None
graphs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graphs)


class AlertGraphInventoryTests(unittest.TestCase):
    """Every rendered condition retains annotation coverage and real diagnostic queries."""

    def test_root_comparison_only(self) -> None:
        """Strip only a root threshold without rewriting inner PromQL logic."""
        assert graphs.diagnostic("((rate(errors_total[5m]) / rate(requests_total[5m])) > 0.1)")[
            :2
        ] == ("(rate(errors_total[5m]) / rate(requests_total[5m]))", 0.1)
        assert graphs.diagnostic('up{note="x > y"} == 0')[:2] == ('up{note="x > y"}', 0)
        parts = graphs.operands("(x > 2) and on(node) (y < 3)")
        assert [p[0] for p in parts] == ["x", "y"]
        assert graphs.diagnostic("a != on(node) b")[0] == "a != on(node) b"

    def test_all_source_rules_have_real_panel_queries_and_priority(self) -> None:
        """Every source variant links to a real panel containing its exact condition."""
        rows = json.loads((ROOT / "docs/monitoring/alert-graphs.inventory.json").read_text())
        # Includes Service-path divergence and distinct absent/down API scrapes.
        expected_source_rule_count = 216
        assert sum(row["alert"] == "LMSWebUnavailable" for row in rows) == 1
        assert any(r["alert"] == "ThanosWarmWorkshopDiskLow" for r in rows)
        assert len(rows) == expected_source_rule_count
        expected_graph_spec_version = 1
        for row in rows:
            with self.subTest(alert=row["alert"]):
                spec = row["graphs"]
                assert spec["version"] == expected_graph_spec_version
                assert spec["graphs"][0]["id"] == "primary"
                for graph in spec["graphs"]:
                    dashboard = json.loads(
                        (
                            ROOT
                            / "charts/monitoring-k3s/alert-dashboards"
                            / (graph["dashboard_uid"] + ".json")
                        ).read_text()
                    )
                    panel = next(p for p in dashboard["panels"] if p["id"] == graph["panel_id"])
                    assert panel["targets"]
                    assert all(t["datasource"]["uid"] == "prometheus" for t in panel["targets"])
                    if graph["id"] == "condition":
                        assert row["expr"] in [t["expr"] for t in panel["targets"]]
        expected_grafana_rule_count = 7
        assert sum(r["owner"] == "grafana-managed" for r in rows) == expected_grafana_rule_count

    def test_generated_files_are_current(self) -> None:
        """Canonical generation must agree with every checked-in diagnostic output."""
        run = command(
            [sys.executable, "-m", "ci.check_alert_graphs"],
            allowed=(0, 1),
        )
        assert run.returncode == 0, run.stderr + run.stdout

    def test_actual_render_has_annotations_without_changing_conditions(self) -> None:
        """Render each owning chart and compare all resource, alert and expression tuples."""
        executable = shutil.which("helm")
        if executable is None:
            message = "Native alert graph coverage requires Helm; no fallback"
            raise FileNotFoundError(message)
        expected = json.loads((ROOT / "docs/monitoring/alert-graphs.inventory.json").read_text())
        for owner in [*graphs.OWNERS, "rancher"]:
            app = yaml.safe_load((ROOT / "deploy/argocd/apps" / (owner + ".yaml")).read_text())
            if owner == "rancher":
                source = next(
                    s
                    for s in app["spec"]["sources"]
                    if s.get("path") == "deploy/platform/rancher/public-entry"
                )
            else:
                source = app["spec"]["source"]
            helm = source["helm"]
            chart = ROOT / source["path"]
            args = [
                executable,
                "template",
                helm["releaseName"],
                str(chart),
                "--namespace",
                app["spec"]["destination"]["namespace"],
            ]
            for file in helm.get("valueFiles", []):
                args += ["-f", str(chart / file)]
            rendered = command(args).stdout
            found = []
            for doc in yaml.safe_load_all(rendered):
                if not isinstance(doc, dict) or doc.get("kind") != "PrometheusRule":
                    continue
                for group in doc["spec"]["groups"]:
                    for rule in group["rules"]:
                        if "alert" not in rule:
                            continue
                        found.append(
                            (
                                doc["metadata"]["name"],
                                rule["alert"],
                                str(rule["expr"]),
                                rule["annotations"]["spi_graphs"],
                            )
                        )
            wanted = [
                (
                    r["resource"],
                    r["alert"],
                    r["expr"],
                    json.dumps(r["graphs"], separators=(",", ":")),
                )
                for r in expected
                if r["owner"] == owner
            ]
            assert sorted(found) == sorted(wanted), owner


if __name__ == "__main__":
    unittest.main()
