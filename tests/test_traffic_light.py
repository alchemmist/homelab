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

    def test_vpn_mode_replaces_top_nodes_without_resizing(self):
        panel = panel_by_id(self.dashboard, 9)
        self.assertEqual(panel['gridPos'], {'x': 4, 'y': 0, 'w': 2, 'h': 2})
        self.assertEqual(panel['title'], '')
        defaults = panel['fieldConfig']['defaults']
        self.assertEqual(defaults['displayName'], 'VPN mode')
        states = defaults['mappings'][0]['options']
        self.assertEqual(states['0'], {'text': 'K3s', 'color': '#26783D'})
        self.assertEqual(states['1'], {'text': 'Fallback', 'color': '#A85D08'})
        self.assertEqual(states['2'], {'text': 'Off', 'color': '#B42332'})
        expr = panel['targets'][0]['expr']
        self.assertIn('socrat_vpn_fallback_active', expr)
        self.assertIn('timestamp(', expr)
        self.assertIn('< 30', expr)
        self.assertIn('or vector(2)', expr)
        self.assertTrue(panel['targets'][0]['instant'])
        ids = {item['id'] for item in self.dashboard['panels']}
        self.assertNotIn(325, ids)
        self.assertNotIn(326, ids)
        self.assertEqual(panel_by_id(self.dashboard, 327)['gridPos']['x'], 2)
        self.assertEqual(panel_by_id(self.dashboard, 328)['gridPos']['x'], 0)

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
            self.assertLessEqual(grid['y'] + grid['h'], 20)
            for assert_key in cells(grid):
                self.assertNotIn(assert_key, occupied, f'panel {panel["id"]} overlaps {occupied.get(assert_key)}')
                occupied[assert_key] = panel['id']
        holes = [(x, y) for y in range(20) for x in range(24)
                 if (x, y) not in occupied]
        approved = json.loads((ROOT / 'tests/fixtures/traffic-light-owner-layout.json').read_text())
        self.assertEqual({str(p['id']): p['gridPos'] for p in self.dashboard['panels']}, approved)
        self.assertEqual(len(holes), 5)  # intentional whitespace in owner layout

    def test_cpu_temperature_bar_removed(self):
        ids = {panel['id'] for panel in self.dashboard['panels']}
        self.assertNotIn(24, ids)

    def test_cluster_health_column_layout(self):
        digits = ['0', '1', '2', '3', '4', '5']
        for i, panel_id in enumerate((901, 902, 903, 904, 926, 927)):
            panel = panel_by_id(self.dashboard, panel_id)
            self.assertEqual(panel['gridPos'], {'x': 23, 'y': i, 'w': 1, 'h': 1})
            self.assertEqual(panel['fieldConfig']['defaults']['displayName'], digits[i])
            self.assertEqual(len(panel['targets']), 1)
        for i, (panel_id, name) in enumerate(((905, 'Home IP'), (906, 'VPS IP'))):
            panel = panel_by_id(self.dashboard, panel_id)
            self.assertEqual(panel['gridPos'], {'x': 23, 'y': 7 - i, 'w': 1, 'h': 1})
            self.assertEqual(panel['fieldConfig']['defaults']['displayName'], name)
            self.assertEqual(len(panel['targets']), 1)
        self.assertNotIn(908, {p['id'] for p in self.dashboard['panels']})  # Owner removed UP.
        chart = panel_by_id(self.dashboard, 907)
        self.assertEqual(chart['gridPos'], {'x': 16, 'y': 10, 'w': 7, 'h': 4})
        self.assertEqual(chart['type'], 'stat')
        history = panel_by_id(self.dashboard, 909)
        self.assertEqual(history['gridPos'], {'x': 0, 'y': 19, 'w': 12, 'h': 1})
        self.assertEqual(history['type'], 'bargauge')

    def test_unmodified_resource_columns(self):
        cpu = panel_by_id(self.dashboard, 21)
        memory = panel_by_id(self.dashboard, 22)
        disk = panel_by_id(self.dashboard, 23)
        for panel in (cpu, memory, disk):
            self.assertEqual(panel['gridPos']['x'] in (8, 13, 18), True)
        self.assertEqual(cpu['gridPos'], {'x': 13, 'y': 0, 'w': 5, 'h': 10})
        self.assertEqual(memory['gridPos'], {'x': 18, 'y': 0, 'w': 5, 'h': 10})
        self.assertEqual(disk['gridPos'], {'x': 8, 'y': 0, 'w': 5, 'h': 10})


    def test_ingress_chart_preserves_live_rps_queries(self):
        panel = panel_by_id(self.dashboard, 334)
        self.assertEqual(len(panel['targets']), 5)
        for target in panel['targets']:
            self.assertIn('sum(rate(traefik_entrypoint_requests_total{', target['expr'])
            self.assertIn('entrypoint=~"web|websecure"', target['expr'])
            self.assertIn('[5m]', target['expr'])

    def test_rps_and_n8n_share_a_shorter_graph_row(self):
        panel = panel_by_id(self.dashboard, 334)
        self.assertEqual(panel['gridPos'], {'x': 0, 'y': 15, 'w': 6, 'h': 4})
        self.assertEqual(panel_by_id(self.dashboard, 920)['gridPos'], {'x': 6, 'y': 10, 'w': 6, 'h': 5})


class TrafficLightQueriesTest(unittest.TestCase):
    def setUp(self):
        self.dashboard = load()

    def node_panel(self, node):
        digit = node.rsplit('-', 1)[1]
        return panel_by_id(self.dashboard, 927 if int(digit) == 5 else 926 if int(digit) == 4 else 901 + int(digit))

    def test_node_tiles_reference_each_node_with_health_priorities(self):
        for node in ('socrat-0', 'socrat-1', 'socrat-2', 'socrat-3', 'socrat-5'):
            expr = self.node_panel(node)['targets'][0]['expr']
            self.assertIn(f'node="{node}"', expr)
            self.assertIn('condition="Ready",status="true"}', expr)
            self.assertIn('condition=~"DiskPressure|MemoryPressure",status="true"', expr)
            self.assertIn('or vector(-2)', expr)
            self.assertIn('2 * (1 -', expr)

    def test_node_tiles_map_every_state_to_color_semantics(self):
        colors = {'0': '#26783D', '1': '#A85D08', '2': '#B42332', '3': '#B42332', '-2': '#555555'}
        for node in ('socrat-0', 'socrat-1', 'socrat-2', 'socrat-3', 'socrat-4', 'socrat-5'):
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
        self.assertEqual(panel['fieldConfig']['defaults']['min'], 0)

    def test_edge_tiles_match_probe_catalog(self):
        text = VALUES.read_text()
        for panel_id, service_id, alert in (
            (905, 'edge-home', 'SocratServiceEdgeHomeUnavailable'),
            (906, 'edge-vps', 'SocratServiceEdgeVpsUnavailable'),
            (928, 'edge-moscow', 'SocratServiceEdgeMoscowUnavailable'),
        ):
            expr = panel_by_id(self.dashboard, panel_id)['targets'][0]['expr']
            self.assertIn(f'service_id="{service_id}"', expr)
            self.assertNotIn('ALERTS', expr)
            self.assertIn('job="public-ip-probes"', expr)
            self.assertIn('probe_observer="socrat-0"', expr)
            self.assertIn('probe_path="direct-home-wan"', expr)
            self.assertIn(f'id: {service_id}\n', text)
            self.assertIn(alert, text)

    def test_n8n_history_is_a_gauge_not_counter_rate(self):
        panel = panel_by_id(self.dashboard, 920)
        self.assertEqual(panel['fieldConfig']['defaults']['custom']['drawStyle'], 'bars')
        expr = panel['targets'][0]['expr']
        self.assertIn('socrat_n8n_starts_window', expr)
        self.assertIn('collection_success', expr)
        self.assertNotIn('increase(', expr)
        self.assertNotIn('rate(', expr)

    def test_dashboard_time_window_is_twelve_hours(self):
        self.assertEqual(self.dashboard['time'], {'from': 'now-12h', 'to': 'now'})

    def test_vpn_preserves_latest_manual_stat_visualization(self):
        panel = panel_by_id(self.dashboard, 907)
        self.assertEqual(panel['type'], 'stat')
        self.assertEqual(panel['gridPos']['y'] + panel['gridPos']['h'], 14)
        self.assertEqual(panel['fieldConfig']['defaults']['min'], 0)
        self.assertNotIn('max', panel['fieldConfig']['defaults'])

    def test_argocd_has_current_state_strip(self):
        panel = panel_by_id(self.dashboard, 909)
        self.assertEqual(panel['type'], 'bargauge')
        self.assertEqual(len(panel['targets']), 1)
        self.assertFalse(panel['options']['legend']['showLegend'])
        self.assertEqual(panel['options']['valueMode'], 'hidden')
        self.assertEqual(panel['options']['namePlacement'], 'hidden')
        self.assertTrue(panel['targets'][0]['instant'])
        self.assertFalse(panel['targets'][0]['range'])
        self.assertNotIn('name!="root"', panel['targets'][0]['expr'])

    def test_new_activity_visuals_have_no_headers_legends_or_period_badges(self):
        for panel_id in (920, 923, 924, 925):
            panel = panel_by_id(self.dashboard, panel_id)
            self.assertEqual(panel.get('title', ''), '')
            self.assertEqual(panel.get('description', ''), '')
            self.assertFalse(panel.get('options', {}).get('legend', {}).get('showLegend', False))
            if panel.get('timeFrom'):
                self.assertTrue(panel['hideTimeOverride'])
        for panel_id in (923, 924, 925):
            panel = panel_by_id(self.dashboard, panel_id)
            self.assertEqual(len(panel['targets']), 1)
            self.assertEqual(panel['options']['orientation'], 'vertical')
            self.assertFalse(panel['options']['wideLayout'])
            self.assertEqual(panel['gridPos']['h'], 2)

    def test_user_approved_resource_panels_remain_unchanged(self):
        approved = json.loads((ROOT / 'tests/fixtures/traffic-light-approved-resources.json').read_text())
        for panel_id, expected in approved.items():
            actual = dict(panel_by_id(self.dashboard, int(panel_id)))
            expected = dict(expected)
            # Approved TMP-1: fixed top labels; metrics, capacity and geometry retained.
            actual.pop('gridPos')
            expected.pop('gridPos')
            self.assertEqual(actual, expected)
        heights = [panel_by_id(self.dashboard, i)['gridPos']['h'] for i in (21, 22, 23)]
        self.assertEqual(heights, [10, 10, 10])

    def test_absolute_resource_values_and_dynamic_capacity(self):
        for panel_id, unit in [(21, 'suffix: cores'), (22, 'bytes'), (23, 'bytes')]:
            panel = panel_by_id(self.dashboard, panel_id)
            defaults = panel['fieldConfig']['defaults']
            self.assertEqual(defaults['unit'], unit)
            self.assertEqual(defaults['thresholds']['mode'], 'percentage')
            self.assertNotIn('max', defaults)
            mappings = panel['transformations'][-1]['options']['mappings']
            self.assertIn({'fieldName': 'Capacity', 'handlerKey': 'max'}, mappings)
            self.assertIn({'fieldName': 'Used', 'handlerKey': 'field.value'}, mappings)
            self.assertEqual(panel['targets'][0]['format'], 'table')
            self.assertIn('nodename', panel['targets'][1]['expr'])
            for target in panel['targets']:
                self.assertNotIn('or vector(0)', target['expr'])
        self.assertIn('node_filesystem_free_bytes', panel_by_id(self.dashboard, 23)['targets'][0]['expr'])

    def test_activity_replaces_incident_list_and_latency(self):
        for panel in self.dashboard['panels']:
            if panel['id'] != 930:  # Owner-approved compact local AI block.
                self.assertNotIn('histogram_quantile', str(panel.get('targets')))
            self.assertNotEqual(panel['type'], 'table')
        self.assertEqual(panel_by_id(self.dashboard, 925)['targets'][0]['legendFormat'], 'n8n · running')
        self.assertIn('window="0"', panel_by_id(self.dashboard, 925)['targets'][0]['expr'])

    def test_owner_removed_up_tile(self):
        self.assertNotIn(908, {p['id'] for p in self.dashboard['panels']})

    def test_platform_tiles_fill_the_gap_under_grafana(self):
        expected = {
            335: ('n8n', 'SocratServiceN8nUnavailable', {'x': 10, 'y': 17, 'w': 2, 'h': 2}),
            336: ('authentik', 'SocratServiceAuthentikUnavailable', {'x': 4, 'y': 9, 'w': 2, 'h': 2}),
            337: ('harbor', 'SocratServiceHarborUnavailable', {'x': 0, 'y': 13, 'w': 2, 'h': 2}),
            338: ('argocd', 'SocratServiceArgocdUnavailable', {'x': 2, 'y': 11, 'w': 2, 'h': 2}),
            339: ('socrat-bot', 'SocratServiceSocratBotUnavailable', {'x': 0, 'y': 10, 'w': 2, 'h': 2}),
        }
        for panel_id, (service_id, alert, grid) in expected.items():
            panel = panel_by_id(self.dashboard, panel_id)
            expr = panel['targets'][0]['expr']
            self.assertIn(f'service_id="{service_id}"', expr)
            self.assertIn(alert, expr)
            self.assertEqual(panel['gridPos'], grid)

    def test_vpn_fraction_tiles_are_removed(self):
        ids = {panel['id'] for panel in self.dashboard['panels']}
        self.assertNotIn(910, ids)
        self.assertNotIn(911, ids)
        names = {item.get('name') for item in self.dashboard.get('templating', {}).get('list', [])}
        self.assertNotIn('vpn_now', names)

    def test_new_panels_have_an_english_description(self):
        for panel in self.dashboard['panels']:
            if panel['id'] >= 901 and panel['id'] not in (909, 920, 923, 924, 925):
                self.assertTrue(panel.get('description', '').strip(), f'panel {panel["id"]}')

    def test_row_panels_have_unique_target_ids_and_series_names(self):
        for panel_id in (901, 902, 903, 904, 926, 927, 905, 906):
            panel = panel_by_id(self.dashboard, panel_id)
            ref_ids = [t['refId'] for t in panel['targets']]
            self.assertEqual(len(ref_ids), len(set(ref_ids)), f'panel {panel_id} duplicate refIds')
            self.assertTrue(panel['fieldConfig']['defaults'].get('displayName', '').strip(),
                            f'panel {panel_id} lacks a tile name')


if __name__ == '__main__':
    unittest.main()
