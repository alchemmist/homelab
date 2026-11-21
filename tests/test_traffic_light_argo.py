"""Tests for Argo-related traffic light behaviour."""

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "traffic_lab", ROOT / "scripts/build-traffic-light-argo.py"
)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

ARGOCD_STRIP_PANEL_ID = 909
MAX_DASHBOARD_BYTES = 240000
ARGO_GRID_COLUMNS = 24
ARGO_GRID_ROWS = 20
ARGO_STATE_CHECK_COUNT = 5


class TrafficLightArgoTest(unittest.TestCase):
    """Tests for TrafficLightArgoTest."""

    def setUp(self):
        self.dashboard = lab.build()
        self.panels = {p["id"]: p for p in self.dashboard["panels"]}

    def test_generated_copy_and_unchanged_original_panels(self):
        assert json.loads(lab.OUTPUT.read_text()) == self.dashboard
        assert self.dashboard["uid"] == "socrat-traffic-light"
        original = json.loads(lab.SOURCE.read_text())
        for p in original["panels"]:
            if p["id"] != ARGOCD_STRIP_PANEL_ID:
                assert self.panels[p["id"]] == p
        assert {k: v for k, v in original.items() if k != "panels"} == {
            k: v for k, v in self.dashboard.items() if k != "panels"
        }
        assert not set(self.panels) & set(range(950, 976))

    def test_current_strip_is_per_application_native_bar_gauge_without_chrome(self):
        p = self.panels[909]
        assert p["type"] == "bargauge"
        assert p["gridPos"] == {"x": 0, "y": 18, "w": 12, "h": 1}
        assert p["title"] == ""
        assert p["transparent"]
        assert p["fieldConfig"]["defaults"]["min"] == 0
        assert (
            p["fieldConfig"]["defaults"]["max"] == 1
        )  # Positive categorical codes: equal full blocks.
        assert p["interval"] == "15s"
        assert p["maxDataPoints"] == 1
        assert len(p["targets"]) == 1
        t = p["targets"][0]
        assert t["instant"]
        assert not t["range"]
        assert t["format"] == "time_series"
        assert t["legendFormat"] == "{{name}}"
        assert t["expr"] == lab.application_query()
        for forbidden in ["argocd_app_sync_total", "topk", "increase(", "count_values("]:
            assert forbidden not in t["expr"]
        assert 'name!="root"' not in t["expr"]
        assert not p["options"]["legend"]["showLegend"]
        assert p["options"]["orientation"] == "vertical"
        assert p["options"]["displayMode"] == "gradient"
        assert p["options"]["valueMode"] == "hidden"
        assert p["options"]["namePlacement"] == "hidden"
        assert p["options"]["textMode"] == "none"
        assert not p["options"]["showUnfilled"]
        assert (
            p["options"]["sizing"] == "manual"
        )  # Auto ignores zero min width and clips narrow panels.
        assert p["options"]["minVizWidth"] == 0
        assert p["options"]["minVizHeight"] == 0
        assert [t["id"] for t in p["transformations"]] == ["seriesToRows", "sortBy", "rowsToFields"]
        assert p["transformations"][1]["options"]["sort"] == [{"field": "Metric", "desc": False}]
        (link,) = p["fieldConfig"]["defaults"]["links"]
        assert link["title"] == "${__field.name}"
        assert (
            link["url"]
            == "https://argocd.socrat.alchemmist.xyz/applications/argocd/${__field.name}"
        )
        assert link["targetBlank"]
        mappings = p["fieldConfig"]["defaults"]["mappings"][0]["options"]
        assert mappings == {
            str(code + 1): {"text": name, "color": color} for name, code, color in lab.STATES
        }

    def test_generator_preserves_manual_argo_geometry_and_thresholds(self):
        original = json.loads(lab.SOURCE.read_text())
        owner = next(p for p in original["panels"] if p["id"] == ARGOCD_STRIP_PANEL_ID)
        panel = self.panels[909]
        assert panel["gridPos"] == owner["gridPos"]
        assert panel.get("pluginVersion") == owner.get("pluginVersion")
        assert (
            panel["fieldConfig"]["defaults"]["thresholds"]
            == owner["fieldConfig"]["defaults"]["thresholds"]
        )

    @unittest.skipUnless(shutil.which("helm"), "helm needed for apply-size regression")
    def test_rendered_apply_annotation_stays_below_kubernetes_limit(self):
        import yaml

        chart = ROOT / "charts/monitoring-k3s"
        rendered = subprocess.check_output(
            [
                "helm",
                "template",
                "monitoring-k3s",
                str(chart),
                "-n",
                "cattle-monitoring-system",
                "-f",
                str(chart / "alert-graphs.values.yaml"),
            ],
            text=True,
        )
        docs = [x for x in yaml.safe_load_all(rendered) if x]
        assert "socrat-traffic-light-tmp-lab-dashboard" not in [x["metadata"]["name"] for x in docs]
        cm = next(x for x in docs if x["metadata"]["name"] == "socrat-traffic-light-dashboard")
        assert len(json.dumps(cm, separators=(",", ":")).encode()) < MAX_DASHBOARD_BYTES
        assert json.loads(next(iter(cm["data"].values()))) == self.dashboard

    def test_nonoverlapping_tv_grid(self):
        occupied = {}
        for p in self.dashboard["panels"]:
            g = p["gridPos"]
            assert g["x"] + g["w"] <= ARGO_GRID_COLUMNS
            assert g["y"] + g["h"] <= ARGO_GRID_ROWS
            for x in range(g["x"], g["x"] + g["w"]):
                for y in range(g["y"], g["y"] + g["h"]):
                    assert (x, y) not in occupied
                    occupied[x, y] = p["id"]
        assert len(self.panels) == len(self.dashboard["panels"])

    @unittest.skipUnless(shutil.which("promtool"), "promtool needed for PromQL semantics")
    def test_promql_partition_latest_labels_and_telemetry_gaps(self):
        def series(name, values="1+0x120"):
            return {"series": name, "values": values}

        def app(name, health="Healthy", sync="Synced", values="1+0x120"):
            return series(
                f'argocd_app_info{{job="socrat-argocd",name="{name}",health_status="{health}",sync_status="{sync}"}}',
                values,
            )

        def checks(counts, when="30m"):
            if len(counts) == ARGO_STATE_CHECK_COUNT:
                counts = counts + [None if counts[0] is None else 0]
            return [
                {
                    "expr": expr,
                    "eval_time": when,
                    "exp_samples": [] if n is None else [{"labels": "{}", "value": n}],
                }
                for (_, expr, _), n in zip(lab.queries()[1], counts)
            ]

        up = series('up{job="socrat-argocd"}')
        mixed = [
            up,
            app("a"),
            app("b", sync="OutOfSync"),
            app("c", "Progressing", "OutOfSync"),
            app("d", "Suspended"),
            app("e", "Degraded", "OutOfSync"),
            app("f", "Unknown"),
            app("g", sync="FutureStatus"),
            app("root", "Degraded"),
        ]
        cases = [
            {
                "interval": "15s",
                "input_series": mixed,
                "promql_expr_test": checks([1, 1, 1, 1, 2, 1]),
            },
            {
                "interval": "15s",
                "input_series": [up, app("a")],
                "promql_expr_test": checks([1, 0, 0, 0, 0]),
            },
            {"interval": "15s", "input_series": [], "promql_expr_test": checks([None] * 5)},
            {
                "interval": "15s",
                "input_series": [series(up["series"], "0+0x120"), app("a")],
                "promql_expr_test": checks([None] * 5),
            },
            {
                "interval": "15s",
                "input_series": [up, app("a", values="1")],
                "promql_expr_test": checks([None] * 5, "3m"),
            },
            # A fresh healthy app cannot hide a second app with stale telemetry.
            {
                "interval": "15s",
                "input_series": [up, app("a"), app("b", values="1")],
                "promql_expr_test": checks([None] * 5, "3m"),
            },
            # The old Healthy label set lingers but the new Degraded one is newer.
            {
                "interval": "15s",
                "input_series": [
                    up,
                    app("a", values="1+0x4"),
                    app("a", "Degraded", "OutOfSync", values="_ _ _ _ _ 1+0x115"),
                ],
                "promql_expr_test": checks([0, 0, 0, 1, 0], "1m30s"),
            },
            # Contradictory same-timestamp label sets still count one app, red wins.
            {
                "interval": "15s",
                "input_series": [up, app("a"), app("a", "Degraded")],
                "promql_expr_test": checks([0, 0, 0, 1, 0]),
            },
        ]

        def app_check(values, when="30m"):
            return {
                "expr": lab.application_query(),
                "eval_time": when,
                "exp_samples": [
                    {"labels": '{name="' + name + '"}', "value": value} for name, value in values
                ],
            }

        cases[0]["promql_expr_test"].append(
            app_check(
                [("a", 5), ("b", 4), ("c", 3), ("d", 6), ("e", 1), ("f", 2), ("g", 2), ("root", 1)]
            )
        )
        cases[1]["promql_expr_test"].append(app_check([("a", 5)]))
        for case in cases[2:6]:
            case["promql_expr_test"].append(app_check([], case["promql_expr_test"][0]["eval_time"]))
        for case in cases[6:]:
            case["promql_expr_test"].append(
                app_check([("a", 1)], case["promql_expr_test"][0]["eval_time"])
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.yaml"
            path.write_text(
                json.dumps({"rule_files": [], "evaluation_interval": "15s", "tests": cases})
            )
            result = subprocess.run(
                ["promtool", "test", "rules", str(path)], capture_output=True, text=True
            )
            assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    unittest.main()
