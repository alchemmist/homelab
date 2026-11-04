import pathlib
import subprocess
import tempfile
import unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class LokiRetentionAlertTests(unittest.TestCase):
    def test_render_and_prometheus_syntax(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(
            ['helm', 'template', 'otel-backends', str(ROOT / 'charts/otel-backends')], text=True)))
        rules = next(d for d in docs if d and d.get('kind') == 'PrometheusRule'
                     and d['metadata']['name'] == 'otel-loki-retention')
        self.assertEqual(rules['metadata']['labels']['release'], 'kube-prometheus-stack')
        alerts = {r['alert']: r for g in rules['spec']['groups'] for r in g['rules']}
        self.assertIn('status="failure"', alerts['LokiRetentionFailed']['expr'])
        self.assertIn('process_start_time_seconds', alerts['LokiRetentionSuccessStale']['expr'])
        self.assertTrue(alerts['LokiRetentionMetricsMissing']['expr'].startswith('absent('))
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml') as f:
            yaml.safe_dump(rules['spec'], f)
            f.flush()
            subprocess.run(['promtool', 'check', 'rules', f.name], check=True)


if __name__ == '__main__':
    unittest.main()
