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

    def test_generated_copy_is_current_and_has_separate_identity(self):
        self.assertEqual(json.loads(lab.OUTPUT.read_text()), self.dashboard)
        self.assertEqual(self.dashboard['uid'], 'socrat-traffic-light-tmp-lab')
        self.assertNotIn('id', self.dashboard)
        self.assertNotIn('version', self.dashboard)

    def test_only_argo_is_changed_no_extra_blocks(self):
        original = json.loads(lab.SOURCE.read_text())
        for p in original['panels']:
            if p['id'] != 909:
                self.assertEqual(self.panels[p['id']], p)
        ids = {p['id'] for p in original['panels']}
        self.assertEqual(set(self.panels) - ids, {970, 971})
        self.assertNotIn(909, self.panels)
        self.assertEqual(self.panels[970]['type'], 'piechart')
        self.assertEqual(self.panels[971]['type'], 'timeseries')
        self.assertEqual(self.panels[970]['options']['pieType'], 'donut')
        for pid in (970, 971):
            for t in self.panels[pid]['targets']:
                self.assertIn('socrat-argocd', t['expr'])
                self.assertNotIn('litellm', t['expr'])
        self.assertEqual(self.panels[971]['interval'], '15m')
        self.assertIn('[15m]', self.panels[971]['targets'][0]['expr'])

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
    def test_promql_categories_are_disjoint_and_gaps_not_healthy(self):
        def series(name, values='1+0x3'):
            return {'series': name, 'values': values}
        up = series('up{job="socrat-argocd"}')
        samples = [up]
        for name, health, sync in [('a', 'Healthy', 'Synced'), ('b', 'Healthy', 'OutOfSync'),
                                   ('c', 'Progressing', 'OutOfSync'), ('d', 'Degraded', 'OutOfSync'),
                                   ('e', 'Unknown', 'Unknown')]:
            samples.append(series(f'argocd_app_info{{job="socrat-argocd",name="{name}",health_status="{health}",sync_status="{sync}"}}'))
        def checks(values, when='2m'):
            return [{'expr': t['expr'], 'eval_time': when,
                     'exp_samples': [] if v is None else [{'labels': '{}', 'value': v}]}
                    for t, v in zip(self.panels[970]['targets'], values)]
        cases = [
            {'interval': '1m', 'input_series': samples, 'promql_expr_test': checks([1]*5)},
            {'interval': '1m', 'input_series': samples[:2], 'promql_expr_test': checks([1, 0, 0, 0, 0])},
            {'interval': '1m', 'input_series': [], 'promql_expr_test': checks([None]*5)},
            {'interval': '1m', 'input_series': [series(s['series'], '1') for s in samples],
             'promql_expr_test': checks([None]*5, '3m')},
            {'interval': '1m', 'input_series': [series(up['series'], '0+0x3')] + samples[1:],
             'promql_expr_test': checks([None]*5)},
        ]
        activity = self.panels[971]['targets'][0]['expr']
        for values, expect in [('0+0x15', 0), ('0+1x15', 15)]:
            cases.append({'interval': '1m', 'input_series': [series(up['series'], '1+0x15'),
                          series('argocd_app_sync_total{job="socrat-argocd",phase="Succeeded",name="a"}', values)],
                          'promql_expr_test': [{'expr': activity, 'eval_time': '15m',
                            'exp_samples': [{'labels': '{phase="Succeeded"}', 'value': expect}]}]})
        cases.append({'interval': '1m', 'input_series': [], 'promql_expr_test': [
            {'expr': activity, 'eval_time': '15m', 'exp_samples': []}]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queries.yaml'
            path.write_text(json.dumps({'rule_files': [], 'evaluation_interval': '1m', 'tests': cases}))
            result = subprocess.run(['promtool', 'test', 'rules', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
