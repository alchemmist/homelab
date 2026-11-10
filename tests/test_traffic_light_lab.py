import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('traffic_lab', ROOT / 'scripts/build-traffic-light-lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class TrafficLightLabTest(unittest.TestCase):
    def setUp(self):
        self.dashboard = lab.build()
        self.panels = {p['id']: p for p in self.dashboard['panels']}

    def test_generated_copy_and_unchanged_original_panels(self):
        self.assertEqual(json.loads(lab.OUTPUT.read_text()), self.dashboard)
        self.assertEqual(self.dashboard['uid'], 'socrat-traffic-light-tmp-lab')
        self.assertNotIn('id', self.dashboard)
        self.assertNotIn('version', self.dashboard)
        original = json.loads(lab.SOURCE.read_text())
        for p in original['panels']:
            if p['id'] != 909:
                self.assertEqual(self.panels[p['id']], p)
        self.assertEqual(set(self.panels) - {p['id'] for p in original['panels']}, {972})
        self.assertNotIn(909, self.panels)
        self.assertFalse(set(self.panels) & set(range(950, 972)))

    def test_map_has_named_apps_fixed_cohort_and_honest_semantics(self):
        p = self.panels[972]
        self.assertEqual(p['type'], 'state-timeline')
        self.assertEqual(p['gridPos'], {'x': 12, 'y': 8, 'w': 6, 'h': 8})
        self.assertEqual(p['targets'][0]['legendFormat'], '{{name}}')
        self.assertIn('@ end()', p['targets'][0]['expr'])
        self.assertIn('topk(8', p['targets'][0]['expr'])
        self.assertIn('Sync does NOT imply a Pod redeploy', p['description'])
        self.assertFalse(p['fieldConfig']['defaults']['custom']['spanNulls'])
        self.assertEqual(p['fieldConfig']['defaults']['mappings'][0]['options']['0']['color'], '#252C36')

    def test_nonoverlapping_tv_grid(self):
        occupied = {}
        for p in self.dashboard['panels']:
            g = p['gridPos']
            self.assertLessEqual(g['x'] + g['w'], 24)
            self.assertLessEqual(g['y'] + g['h'], 16)
            for x in range(g['x'], g['x'] + g['w']):
                for y in range(g['y'], g['y'] + g['h']):
                    self.assertNotIn((x, y), occupied)
                    occupied[x, y] = p['id']
        self.assertEqual(len(self.panels), len(self.dashboard['panels']))

    @unittest.skipUnless(shutil.which('promtool'), 'promtool needed for PromQL semantics')
    def test_promql_priority_cohort_gaps_and_sync_pulse(self):
        def series(name, values='1+0x30'):
            return {'series': name, 'values': values}
        def app(name, health='Healthy', sync='Synced'):
            return series(f'argocd_app_info{{job="socrat-argocd",name="{name}",health_status="{health}",sync_status="{sync}"}}')
        def counter(name, phase='Succeeded', values='0+1x30'):
            return series(f'argocd_app_sync_total{{job="socrat-argocd",name="{name}",phase="{phase}"}}', values)
        def samples(values):
            return [{'labels': '{name="' + n + '"}', 'value': v} for n, v in values.items()]
        activity, cohort, selected = lab.queries('30m')
        up = series('up{job="socrat-argocd"}')
        inputs = [up, app('quiet'), app('sync'), counter('sync'),
                  app('drift', sync='OutOfSync'), counter('drift'),
                  app('working', 'Progressing', 'OutOfSync'), counter('working'),
                  app('failed'), counter('failed', 'Failed'),
                  app('unhealthy', 'Degraded', 'OutOfSync'), counter('unhealthy', 'Failed'),
                  app('unknown', 'Unknown', 'Unknown')]
        values = {'quiet': 0, 'sync': 1, 'drift': 2, 'working': 3, 'failed': 4, 'unhealthy': 5, 'unknown': 6}
        cases = [
            {'interval': '1m', 'input_series': inputs, 'promql_expr_test': [
                {'expr': activity, 'eval_time': '30m', 'exp_samples': samples(values)},
                {'expr': selected, 'eval_time': '30m', 'exp_samples': samples({n: v for n, v in values.items() if n != 'quiet'})}]},
            {'interval': '1m', 'input_series': [], 'promql_expr_test': [
                {'expr': activity, 'eval_time': '30m', 'exp_samples': []},
                {'expr': selected, 'eval_time': '30m', 'exp_samples': []}]},
            {'interval': '1m', 'input_series': [series(up['series'], '1'), series(app('quiet')['series'], '1')],
             'promql_expr_test': [{'expr': activity, 'eval_time': '3m', 'exp_samples': []}]},
            {'interval': '1m', 'input_series': [series(up['series'], '0+0x30'), app('quiet')],
             'promql_expr_test': [{'expr': activity, 'eval_time': '30m', 'exp_samples': []}]},
            {'interval': '1m', 'input_series': [up, app('pulse'), counter('pulse', values='0+0x10 1+0x19')],
             'promql_expr_test': [
                 {'expr': activity, 'eval_time': '12m', 'exp_samples': samples({'pulse': 1})},
                 {'expr': activity, 'eval_time': '22m', 'exp_samples': samples({'pulse': 0})}]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queries.yaml'
            path.write_text(json.dumps({'rule_files': [], 'evaluation_interval': '1m', 'tests': cases}))
            result = subprocess.run(['promtool', 'test', 'rules', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
