"""Overview keeps semicircular gauges; Traffic Light uses separate bar gauges."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OverviewCapacityTest(unittest.TestCase):
    def test_capacity_uses_original_native_gauge_options(self):
        dashboard = json.loads((ROOT / 'charts/monitoring-k3s/dashboards/overview.json').read_text())
        self.assertEqual(dashboard['uid'], 'socrat-overview')
        panels = {p['id']: p for p in dashboard['panels']}
        for panel_id in (27, 28, 29):
            p = panels[panel_id]
            self.assertEqual(p['type'], 'gauge')
            self.assertEqual(p['options'], {
                'reduceOptions': {'values': False, 'calcs': ['lastNotNull'], 'fields': ''},
                'orientation': 'auto', 'showThresholdLabels': False,
                'showThresholdMarkers': True, 'text': {'titleSize': 12, 'valueSize': 28}})
            self.assertEqual(p['fieldConfig']['defaults']['unit'], 'percent')
            self.assertEqual(p['fieldConfig']['defaults']['min'], 0)
            self.assertEqual(p['fieldConfig']['defaults']['max'], 100)
            self.assertEqual([t['refId'] for t in p['targets']], ['A', 'B', 'C'])
            self.assertEqual([t['id'] for t in p['transformations']],
                             ['joinByField', 'organize', 'filterByValue', 'rowsToFields'])

    def test_traffic_light_resource_bars_stay_independent(self):
        d = json.loads((ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json').read_text())
        for p in d['panels']:
            if p['id'] in (21, 22, 23):
                self.assertEqual(p['type'], 'bargauge')
                self.assertEqual(p['options']['namePlacement'], 'top')


if __name__ == '__main__':
    unittest.main()
