import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
VALUES = ROOT / 'charts/monitoring-k3s/values.yaml'


def load():
    return json.loads(DASHBOARD.read_text())


def panel_by_id(dashboard, panel_id):
    return next(item for item in dashboard['panels'] if item.get('id') == panel_id)


def cells(grid):
    """Grid cells covered by a panel."""
    x = int(grid['x'])
    y = int(grid['y'])
    w = int(grid['w'])
    h = int(grid['h'])
    return [(cx, cy) for cx in range(x, x + w) for cy in range(y, y + h)]


class TrafficLightLayoutTest(unittest.TestCase):
    def setUp(self):
        self.dashboard = load()

    def test_panels_use_the_integer_tv_grid(self):
        for panel in self.dashboard['panels']:
            grid = panel['gridPos']
            self.assertIsInstance(grid['x'], int, f'panel {panel["id"]} fractional x')
            self.assertIsInstance(grid['y'], int, f'panel {panel["id"]} fractional y')
            self.assertIsInstance(grid['w'], int, f'panel {panel["id"]} fractional w')
            self.assertIsInstance(grid['h'], int, f'panel {panel["id"]} fractional h')

    def test_panels_fill_the_tv_grid_without_holes_or_overlaps(self):
        occupied = {}
        for panel in self.dashboard['panels']:
            grid = panel['gridPos']
            self.assertLessEqual(grid['x'] + grid['w'], 24)
            self.assertLessEqual(grid['y'] + grid['h'], 15)
            for assert_key in cells(grid):
                self.assertNotIn(assert_key, occupied, f'panel {panel["id"]} overlaps {occupied.get(assert_key)}')
                occupied[assert_key] = panel['id']
        holes = [(x, y) for y in range(15) for x in range(24)
                 if (x, y) not in occupied]
        self.assertEqual(holes, [])

    def test_cpu_temperature_bar_removed(self):
        ids = {panel['id'] for panel in self.dashboard['panels']}
        self.assertNotIn(24, ids)

    def test_cluster_health_column_layout(self):
        digits = ['0', '1', '2', '3']
        for i, panel_id in enumerate((901, 902, 903, 904)):
            panel = panel_by_id(self.dashboard, panel_id)
            self.assertEqual(panel['gridPos'], {'x': 19 + i, 'y': 7, 'w': 1, 'h': 1})
            self.assertEqual(panel['fieldConfig']['defaults']['displayName'], digits[i])
            self.assertEqual(len(panel['targets']), 1)
        for i, (panel_id, name) in enumerate(((905, 'Home IP'), (906, 'VPS IP'))):
            panel = panel_by_id(self.dashboard, panel_id)
            self.assertEqual(panel['gridPos'], {'x': 19 + i * 2, 'y': 8, 'w': 2, 'h': 1})
            self.assertEqual(panel['fieldConfig']['defaults']['displayName'], name)
            self.assertEqual(len(panel['targets']), 1)
        up = panel_by_id(self.dashboard, 908)
        self.assertEqual(up['gridPos'], {'x': 23, 'y': 7, 'w': 1, 'h': 2})
        self.assertEqual(up['fieldConfig']['defaults']['displayName'], 'UP')
        chart = panel_by_id(self.dashboard, 907)
        self.assertEqual(chart['gridPos'], {'x': 19, 'y': 12, 'w': 5, 'h': 3})
        self.assertEqual(chart['type'], 'timeseries')
        history = panel_by_id(self.dashboard, 909)
        self.assertEqual(history['gridPos'], {'x': 19, 'y': 9, 'w': 5, 'h': 3})
        self.assertEqual(history['type'], 'timeseries')

    def test_unmodified_resource_columns(self):
        cpu = panel_by_id(self.dashboard, 21)
        memory = panel_by_id(self.dashboard, 22)
        disk = panel_by_id(self.dashboard, 23)
        for panel in (cpu, memory, disk):
            self.assertEqual(panel['gridPos']['x'] in (14, 19), True)
        self.assertEqual(cpu['gridPos'], {'x': 14, 'y': 0, 'w': 5, 'h': 7})
        self.assertEqual(memory['gridPos'], {'x': 19, 'y': 0, 'w': 5, 'h': 7})
        self.assertEqual(disk['gridPos'], {'x': 14, 'y': 7, 'w': 5, 'h': 8})

    def test_rps_chart_keeps_full_width(self):
        panel = panel_by_id(self.dashboard, 334)
        self.assertEqual(panel['gridPos'], {'x': 0, 'y': 10, 'w': 14, 'h': 5})


class TrafficLightQueriesTest(unittest.TestCase):
    def setUp(self):
        self.dashboard = load()

    def node_panel(self, node):
        digit = node.rsplit('-', 1)[1]
        return panel_by_id(self.dashboard, 901 + int(digit))

    def test_node_tiles_reference_each_node_with_health_priorities(self):
        for node in ('socrat-0', 'socrat-1', 'socrat-2', 'socrat-3'):
            expr = self.node_panel(node)['targets'][0]['expr']
            self.assertIn(f'node="{node}"', expr)
            self.assertIn('condition="Ready",status="true"}', expr)
            self.assertIn('condition=~"DiskPressure|MemoryPressure",status="true"', expr)
            self.assertIn('or vector(-2)', expr)
            self.assertIn('2 * (1 -', expr)

    def test_node_tiles_map_every_state_to_color_semantics(self):
        colors = {'0': '#26783D', '1': '#A85D08', '2': '#B42332', '3': '#B42332', '-2': '#555555'}
        for node in ('socrat-0', 'socrat-1', 'socrat-2', 'socrat-3'):
            mappings = self.node_panel(node)['fieldConfig']['defaults']['mappings'][0]['options']
            for value, color in colors.items():
                self.assertIn(value, mappings)
                self.assertEqual(mappings[value]['color'], color)

    def test_vpn_chart_uses_freshness_guarded_textfile_metrics(self):
        expr = panel_by_id(self.dashboard, 907)['targets'][0]['expr']
        self.assertIn('socrat_vpn_active_clients', expr)
        self.assertIn('socrat_vpn_collection_success == 1', expr)
        self.assertIn('socrat_vpn_collection_timestamp_seconds < 90', expr)
        panel = panel_by_id(self.dashboard, 907)
        self.assertFalse(panel['fieldConfig']['defaults']['custom']['spanNulls'])
        self.assertEqual(panel['fieldConfig']['defaults']['min'], 0)

    def test_edge_tiles_match_probe_catalog(self):
        text = VALUES.read_text()
        for panel_id, service_id, alert in (
            (905, 'edge-home', 'SocratServiceEdgeHomeUnavailable'),
            (906, 'edge-vps', 'SocratServiceEdgeVpsUnavailable'),
        ):
            expr = panel_by_id(self.dashboard, panel_id)['targets'][0]['expr']
            self.assertIn(f'service_id="{service_id}"', expr)
            self.assertIn(alert, expr)
            self.assertIn(f'id: {service_id}\n', text)
            self.assertIn(alert, text)

    def test_tv_charts_hide_axes_but_keep_grid(self):
        for panel_id in (907, 909):
            custom = panel_by_id(self.dashboard, panel_id)['fieldConfig']['defaults']['custom']
            self.assertEqual(custom['axisPlacement'], 'hidden')
            self.assertTrue(custom['axisGridShow'])

    def test_vpn_panel_bindings(self):
        panel = panel_by_id(self.dashboard, 907)
        self.assertEqual(panel['title'], '')
        self.assertEqual(panel['fieldConfig']['defaults']['min'], 0)
        self.assertEqual(panel['fieldConfig']['defaults']['max'], 15)
        # no traffic-light zones: a single calm threshold and fixed blue fill
        custom = panel['fieldConfig']['defaults']['custom']
        self.assertEqual(custom['thresholdsStyle'], {'mode': 'off'})
        self.assertEqual(len(panel['fieldConfig']['defaults']['thresholds']['steps']), 1)

    def test_cluster_cpu_history_shows_average_utilization(self):
        panel = panel_by_id(self.dashboard, 909)
        target = panel['targets'][0]
        self.assertEqual(target['refId'], 'A')
        self.assertIn('node_cpu_seconds_total', target['expr'])
        self.assertIn("mode=\"idle\"", target['expr'])
        self.assertIn('avg(rate(', target['expr'])
        self.assertNotIn(' by ', target['expr'])
        defaults = panel['fieldConfig']['defaults']
        self.assertEqual(defaults['unit'], 'percent')
        self.assertEqual((defaults['min'], defaults['max']), (0, 100))
        self.assertEqual([s['color'] for s in defaults['thresholds']['steps']],
                         ['#26783D', '#A85D08', '#B42332'])

    def test_up_tile_counts_ready_nodes_with_quorum_thresholds(self):
        up = panel_by_id(self.dashboard, 908)
        expr = up['targets'][0]['expr']
        self.assertIn('sum(kube_node_status_condition{condition="Ready",status="true"})', expr)
        self.assertIn('or vector(-2)', expr)
        self.assertIn('< 120', expr)
        steps = up['fieldConfig']['defaults']['thresholds']['steps']
        self.assertEqual(steps[0]['color'], '#B42332')
        self.assertEqual(steps[1], {'color': '#A85D08', 'value': 3})
        self.assertEqual(steps[2], {'color': '#26783D', 'value': 4})

    def test_new_panels_have_an_english_description(self):
        for panel in self.dashboard['panels']:
            if panel['id'] >= 901:
                self.assertTrue(panel.get('description', '').strip(), f'panel {panel["id"]}')

    def test_row_panels_have_unique_target_ids_and_series_names(self):
        for panel_id in (901, 902, 903, 904, 905, 906):
            panel = panel_by_id(self.dashboard, panel_id)
            ref_ids = [t['refId'] for t in panel['targets']]
            self.assertEqual(len(ref_ids), len(set(ref_ids)), f'panel {panel_id} duplicate refIds')
            self.assertTrue(panel['fieldConfig']['defaults'].get('displayName', '').strip(),
                            f'panel {panel_id} lacks a tile name')


if __name__ == '__main__':
    unittest.main()
