"""Tests for the traffic light status indicator."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "charts/monitoring-k3s/dashboards/traffic-light.json"
VALUES = ROOT / "charts/monitoring-k3s/values.yaml"

TV_GRID_COLUMNS = 24
TV_GRID_ROWS = 19
OWNER_LAYOUT_HOLE_COUNT = 33
RETIRED_TOP_ROW_NODE_IDS = (325, 326)
NODE_COLUMN_X = {327: 2, 328: 0}
LEGACY_NODE_TILE_BASE_ID = 901
NODE_TILE_ID_BY_DIGIT = {4: 926, 5: 927}
CPU_TEMP_PANEL_ID = 24
REMOVED_UP_TILE_ID = 908
REMOVED_VPN_FRACTION_TILE_IDS = (910, 911)
INGRESS_RPS_TARGET_COUNT = 5
ACTIVITY_ROW_BOTTOM_Y = 14
COMPACT_READOUT_HEIGHT = 2
LOCAL_AI_PANEL_ID = 930
DISK_IO_PANEL_ID = 23


def load():
    return json.loads(DASHBOARD.read_text())


def panel_by_id(dashboard, panel_id):
    return next(item for item in dashboard["panels"] if item.get("id") == panel_id)


def cells(grid):
    """Grid cells covered by a panel."""
    x = int(grid["x"])
    y = int(grid["y"])
    w = int(grid["w"])
    h = int(grid["h"])
    return [(cx, cy) for cx in range(x, x + w) for cy in range(y, y + h)]


class TrafficLightLayoutTest(unittest.TestCase):
    """Tests for TrafficLightLayoutTest."""
    def setUp(self):
        self.dashboard = load()

    def test_vpn_mode_replaces_top_nodes_without_resizing(self):
        panel = panel_by_id(self.dashboard, 9)
        assert panel["gridPos"] == {"x": 4, "y": 0, "w": 2, "h": 2}
        assert panel["title"] == ""
        defaults = panel["fieldConfig"]["defaults"]
        assert defaults["displayName"] == "VPN mode"
        states = defaults["mappings"][0]["options"]
        assert states["0"] == {"text": "K3S", "color": "#26783D"}
        assert states["1"] == {"text": "OS", "color": "#A85D08"}
        assert states["2"] == {"text": "OFF", "color": "#B42332"}
        expr = panel["targets"][0]["expr"]
        assert "socrat_vpn_component_runtime" in expr
        assert 'component="relay"' in expr
        assert 'component="backend"' in expr
        assert "timestamp(" in expr
        assert "< 90" in expr
        assert "or vector(-2)" in expr
        assert states["-2"]["text"] == "NO DATA"
        assert panel["targets"][0]["instant"]
        ids = {item["id"] for item in self.dashboard["panels"]}
        assert ids.isdisjoint(RETIRED_TOP_ROW_NODE_IDS)
        for node_panel_ids, x in NODE_COLUMN_X.items():
            assert panel_by_id(self.dashboard, node_panel_ids)["gridPos"]["x"] == x

    def test_panels_use_the_integer_tv_grid(self):
        for panel in self.dashboard["panels"]:
            grid = panel["gridPos"]
            assert isinstance(grid["x"], int), f"panel {panel['id']} fractional x"
            assert isinstance(grid["y"], int), f"panel {panel['id']} fractional y"
            assert isinstance(grid["w"], int), f"panel {panel['id']} fractional w"
            assert isinstance(grid["h"], int), f"panel {panel['id']} fractional h"

    def test_panels_fill_the_tv_grid_without_holes_or_overlaps(self):
        occupied = {}
        for panel in self.dashboard["panels"]:
            grid = panel["gridPos"]
            assert grid["x"] + grid["w"] <= TV_GRID_COLUMNS
            assert grid["y"] + grid["h"] <= TV_GRID_ROWS
            for assert_key in cells(grid):
                assert assert_key not in occupied, (
                    f"panel {panel['id']} overlaps {occupied.get(assert_key)}"
                )
                occupied[assert_key] = panel["id"]
        holes = [(x, y) for y in range(19) for x in range(24) if (x, y) not in occupied]
        approved = json.loads((ROOT / "tests/fixtures/traffic-light-owner-layout.json").read_text())
        assert {str(p["id"]): p["gridPos"] for p in self.dashboard["panels"]} == approved
        assert len(holes) == OWNER_LAYOUT_HOLE_COUNT  # intentional whitespace in owner layout

    def test_cpu_temperature_bar_removed(self):
        ids = {panel["id"] for panel in self.dashboard["panels"]}
        assert CPU_TEMP_PANEL_ID not in ids

    def test_cluster_health_column_layout(self):
        digits = ["0", "1", "2", "3", "4", "5"]
        for i, panel_id in enumerate((901, 902, 903, 904, 926, 927)):
            panel = panel_by_id(self.dashboard, panel_id)
            assert panel["gridPos"] == {"x": 23, "y": i, "w": 1, "h": 1}
            assert panel["fieldConfig"]["defaults"]["displayName"] == digits[i]
            assert len(panel["targets"]) == 1
        for i, (panel_id, name) in enumerate(((905, "Home IP"), (906, "VPS IP"))):
            panel = panel_by_id(self.dashboard, panel_id)
            assert panel["gridPos"] == {"x": 23, "y": 7 - i, "w": 1, "h": 1}
            assert panel["fieldConfig"]["defaults"]["displayName"] == name
            assert len(panel["targets"]) == 1
        assert REMOVED_UP_TILE_ID not in {
            p["id"] for p in self.dashboard["panels"]
        }  # Owner removed UP.
        chart = panel_by_id(self.dashboard, 907)
        assert chart["gridPos"] == {"x": 16, "y": 10, "w": 8, "h": 4}
        assert chart["type"] == "stat"
        history = panel_by_id(self.dashboard, 909)
        assert history["gridPos"] == {"x": 0, "y": 18, "w": 12, "h": 1}
        assert history["type"] == "bargauge"

    def test_unmodified_resource_columns(self):
        cpu = panel_by_id(self.dashboard, 21)
        memory = panel_by_id(self.dashboard, 22)
        disk = panel_by_id(self.dashboard, 23)
        for panel in (cpu, memory, disk):
            assert panel["gridPos"]["x"] in (8, 13, 18)
        assert cpu["gridPos"] == {"x": 13, "y": 0, "w": 5, "h": 10}
        assert memory["gridPos"] == {"x": 18, "y": 0, "w": 5, "h": 10}
        assert disk["gridPos"] == {"x": 8, "y": 0, "w": 5, "h": 10}

    def test_ingress_chart_preserves_live_rps_queries(self):
        panel = panel_by_id(self.dashboard, 334)
        assert len(panel["targets"]) == INGRESS_RPS_TARGET_COUNT
        for target in panel["targets"]:
            assert "sum(rate(traefik_entrypoint_requests_total{" in target["expr"]
            assert 'entrypoint=~"web|websecure"' in target["expr"]
            assert "[5m]" in target["expr"]

    def test_rps_and_n8n_share_a_shorter_graph_row(self):
        panel = panel_by_id(self.dashboard, 334)
        assert panel["gridPos"] == {"x": 0, "y": 14, "w": 6, "h": 4}
        assert panel_by_id(self.dashboard, 920)["gridPos"] == {"x": 6, "y": 10, "w": 6, "h": 4}


class TrafficLightQueriesTest(unittest.TestCase):
    """Tests for TrafficLightQueriesTest."""
    def setUp(self):
        self.dashboard = load()

    def node_panel(self, node):
        digit = node.rsplit("-", 1)[1]
        return panel_by_id(
            self.dashboard,
            NODE_TILE_ID_BY_DIGIT.get(int(digit), LEGACY_NODE_TILE_BASE_ID + int(digit)),
        )

    def test_node_tiles_reference_each_node_with_health_priorities(self):
        for node in ("socrat-0", "socrat-1", "socrat-2", "socrat-3", "socrat-4", "socrat-5"):
            expr = self.node_panel(node)["targets"][0]["expr"]
            assert f'node="{node}"' in expr
            assert 'condition="Ready",status="true"}' in expr
            assert 'condition=~"DiskPressure|MemoryPressure",status="true"' in expr
            assert "or vector(-2)" in expr
            assert "2 * (1 -" in expr

    def test_node_tiles_map_every_state_to_color_semantics(self):
        colors = {"0": "#26783D", "1": "#A85D08", "2": "#B42332", "3": "#B42332", "-2": "#555555"}
        for node in ("socrat-0", "socrat-1", "socrat-2", "socrat-3", "socrat-4", "socrat-5"):
            mappings = self.node_panel(node)["fieldConfig"]["defaults"]["mappings"][0]["options"]
            for value, color in colors.items():
                assert value in mappings
                assert mappings[value]["color"] == color

    def test_vpn_chart_uses_freshness_guarded_textfile_metrics(self):
        expr = panel_by_id(self.dashboard, 907)["targets"][0]["expr"]
        assert "socrat_vpn_active_clients" in expr
        assert "socrat_vpn_collection_success == 1" in expr
        assert "socrat_vpn_collection_timestamp_seconds < 90" in expr
        panel = panel_by_id(self.dashboard, 907)
        assert panel["fieldConfig"]["defaults"]["min"] == 0

    def test_edge_tiles_match_probe_catalog(self):
        text = VALUES.read_text()
        for panel_id, service_id, alert in (
            (905, "edge-home", "SocratServiceEdgeHomeUnavailable"),
            (906, "edge-vps", "SocratServiceEdgeVpsUnavailable"),
            (928, "edge-moscow", "SocratServiceEdgeMoscowUnavailable"),
        ):
            expr = panel_by_id(self.dashboard, panel_id)["targets"][0]["expr"]
            assert f'service_id="{service_id}"' in expr
            assert "ALERTS" not in expr
            assert 'job="public-ip-probes"' in expr
            assert 'probe_observer="socrat-0"' in expr
            assert 'probe_path="direct-home-wan-v2"' in expr
            assert f"id: {service_id}\n" in text
            assert alert in text

    def test_n8n_history_is_a_gauge_not_counter_rate(self):
        panel = panel_by_id(self.dashboard, 920)
        assert panel["fieldConfig"]["defaults"]["custom"]["drawStyle"] == "bars"
        expr = panel["targets"][0]["expr"]
        assert "socrat_n8n_starts_window" in expr
        assert "collection_success" in expr
        assert "increase(" not in expr
        assert "rate(" not in expr

    def test_dashboard_time_window_is_twelve_hours(self):
        assert self.dashboard["time"] == {"from": "now-12h", "to": "now"}

    def test_vpn_preserves_latest_manual_stat_visualization(self):
        panel = panel_by_id(self.dashboard, 907)
        assert panel["type"] == "stat"
        assert panel["gridPos"]["y"] + panel["gridPos"]["h"] == ACTIVITY_ROW_BOTTOM_Y
        assert panel["fieldConfig"]["defaults"]["min"] == 0
        assert "max" not in panel["fieldConfig"]["defaults"]

    def test_argocd_has_current_state_strip(self):
        panel = panel_by_id(self.dashboard, 909)
        assert panel["type"] == "bargauge"
        assert len(panel["targets"]) == 1
        assert not panel["options"]["legend"]["showLegend"]
        assert panel["options"]["valueMode"] == "hidden"
        assert panel["options"]["namePlacement"] == "hidden"
        assert panel["targets"][0]["instant"]
        assert not panel["targets"][0]["range"]
        assert 'name!="root"' not in panel["targets"][0]["expr"]

    def test_new_activity_visuals_have_no_headers_legends_or_period_badges(self):
        for panel_id in (920,):
            panel = panel_by_id(self.dashboard, panel_id)
            assert panel.get("title", "") == ""
            assert panel.get("description", "") == ""
            assert not panel.get("options", {}).get("legend", {}).get("showLegend", False)
            if panel.get("timeFrom"):
                assert panel["hideTimeOverride"]
        for panel_id in ():  # owner removed compact n8n readouts
            panel = panel_by_id(self.dashboard, panel_id)
            assert len(panel["targets"]) == 1
            assert panel["options"]["orientation"] == "vertical"
            assert not panel["options"]["wideLayout"]
            assert panel["gridPos"]["h"] == COMPACT_READOUT_HEIGHT

    def test_user_approved_resource_panels_remain_unchanged(self):
        approved = json.loads(
            (ROOT / "tests/fixtures/traffic-light-approved-resources.json").read_text()
        )
        for panel_id, expected in approved.items():
            actual = dict(panel_by_id(self.dashboard, int(panel_id)))
            expected = dict(expected)
            # Approved TMP-1: fixed top labels; metrics, capacity and geometry retained.
            actual.pop("gridPos")
            expected.pop("gridPos")
            assert actual == expected
        heights = [panel_by_id(self.dashboard, i)["gridPos"]["h"] for i in (21, 22, 23)]
        assert heights == [10, 10, 10]

    def test_absolute_resource_values_and_dynamic_capacity(self):
        for panel_id, unit in [(21, "suffix: cores"), (22, "bytes"), (23, "bytes")]:
            panel = panel_by_id(self.dashboard, panel_id)
            defaults = panel["fieldConfig"]["defaults"]
            assert defaults["unit"] == unit
            assert defaults["thresholds"]["mode"] == "percentage"
            assert "max" not in defaults
            mappings = panel["transformations"][-1]["options"]["mappings"]
            assert {"fieldName": "Capacity", "handlerKey": "max"} in mappings
            assert {"fieldName": "Used", "handlerKey": "field.value"} in mappings
            assert panel["targets"][0]["format"] == "table"
            assert "nodename" in panel["targets"][1]["expr"]
            for target in panel["targets"]:
                assert "or vector(0)" not in target["expr"]
        assert (
            "node_filesystem_free_bytes"
            in panel_by_id(self.dashboard, DISK_IO_PANEL_ID)["targets"][0]["expr"]
        )

    def test_activity_replaces_incident_list_and_latency(self):
        for panel in self.dashboard["panels"]:
            if panel["id"] != LOCAL_AI_PANEL_ID:  # Owner-approved compact local AI block.
                assert "histogram_quantile" not in str(panel.get("targets"))
            assert panel["type"] != "table"
        assert not {923, 924, 925, 930} & {p["id"] for p in self.dashboard["panels"]}

    def test_owner_removed_up_tile(self):
        assert REMOVED_UP_TILE_ID not in {p["id"] for p in self.dashboard["panels"]}

    def test_platform_tiles_fill_the_gap_under_grafana(self):
        expected = {
            335: ("n8n", "SocratServiceN8nUnavailable", {"h": 1, "w": 2, "x": 6, "y": 9}),
            336: (
                "authentik",
                "SocratServiceAuthentikUnavailable",
                {"h": 2, "w": 2, "x": 4, "y": 7},
            ),
            337: ("harbor", "SocratServiceHarborUnavailable", {"h": 1, "w": 2, "x": 0, "y": 11}),
            338: ("argocd", "SocratServiceArgocdUnavailable", {"h": 2, "w": 2, "x": 2, "y": 9}),
            339: (
                "socrat-bot",
                "SocratServiceSocratBotUnavailable",
                {"h": 2, "w": 2, "x": 0, "y": 8},
            ),
        }
        for panel_id, (service_id, alert, grid) in expected.items():
            panel = panel_by_id(self.dashboard, panel_id)
            expr = panel["targets"][0]["expr"]
            assert f'service_id="{service_id}"' in expr
            assert alert in expr
            assert panel["gridPos"] == grid

    def test_vpn_fraction_tiles_are_removed(self):
        ids = {panel["id"] for panel in self.dashboard["panels"]}
        assert ids.isdisjoint(REMOVED_VPN_FRACTION_TILE_IDS)
        names = {item.get("name") for item in self.dashboard.get("templating", {}).get("list", [])}
        assert "vpn_now" not in names

    def test_new_panels_have_an_english_description(self):
        for panel in self.dashboard["panels"]:
            if panel["id"] >= LEGACY_NODE_TILE_BASE_ID and panel["id"] not in (
                909,
                920,
                923,
                924,
                925,
                938,
            ):
                assert panel.get("description", "").strip(), f"panel {panel['id']}"

    def test_row_panels_have_unique_target_ids_and_series_names(self):
        for panel_id in (901, 902, 903, 904, 926, 927, 905, 906):
            panel = panel_by_id(self.dashboard, panel_id)
            ref_ids = [t["refId"] for t in panel["targets"]]
            assert len(ref_ids) == len(set(ref_ids)), f"panel {panel_id} duplicate refIds"
            assert panel["fieldConfig"]["defaults"].get("displayName", "").strip(), (
                f"panel {panel_id} lacks a tile name"
            )


if __name__ == "__main__":
    unittest.main()
