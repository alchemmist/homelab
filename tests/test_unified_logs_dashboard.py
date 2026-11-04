"""Offline contracts: dashboard provisioning and native Loki queries, no credentials."""
import json
from pathlib import Path
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


class UnifiedLogsDashboardTest(unittest.TestCase):
    def setUp(self):
        self.dashboard = json.loads((ROOT / 'charts/monitoring-k3s/dashboards/logs.json').read_text())

    def test_provisioning(self):
        template = (ROOT / 'charts/monitoring-k3s/templates/socrat-dashboard.yaml').read_text()
        self.assertIn('"logs"', template)
        self.assertIn('grafana_dashboard: "1"', template)
        self.assertEqual(self.dashboard['uid'], 'socrat-unified-logs')

    def test_selectors_and_queries(self):
        variables = self.dashboard['templating']['list']
        self.assertEqual([v['name'] for v in variables], ['service', 'namespace', 'node', 'severity'])
        for variable in variables:
            self.assertTrue(variable['multi'])
            self.assertEqual(variable['allValue'], '.+' if variable['name'] == 'service' else '.*')
        for panel in self.dashboard['panels']:
            self.assertEqual(panel['datasource']['uid'], 'loki')
            expression = panel['targets'][0]['expr']
            for name in ['service', 'namespace', 'node', 'severity']:
                self.assertIn('${' + name + ':regex}', expression)
            self.assertNotIn('| json', expression)
        self.assertFalse(any(p['type'] == 'text' for p in self.dashboard['panels']))
        self.assertEqual(min(p['gridPos']['y'] for p in self.dashboard['panels']), 0)

    def test_explore_preserves_queries_and_time(self):
        url = self.dashboard['links'][0]['url']
        state = json.loads(unquote(url.split('&left=', 1)[1]))
        self.assertEqual(state['range'], {'from': '${__from}', 'to': '${__to}'})
        self.assertEqual(state['queries'][0]['expr'], self.dashboard['panels'][-1]['targets'][0]['expr'])
        self.assertEqual(state['datasource'], 'loki')


if __name__ == '__main__':
    unittest.main()
