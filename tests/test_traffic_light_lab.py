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
        self.assertEqual(set(self.panels) - {p['id'] for p in original['panels']}, {975})
        self.assertNotIn(909, self.panels)
        self.assertFalse(set(self.panels) & set(range(950, 975)))

    def test_landscape_is_stacked_with_five_stable_categories(self):
        p = self.panels[975]
        self.assertEqual(p['type'], 'timeseries')
        self.assertEqual(p['gridPos'], {'x': 12, 'y': 8, 'w': 6, 'h': 7})
        self.assertEqual(p['title'], '')
        self.assertEqual(p['interval'], '15s')
        self.assertGreaterEqual(p['maxDataPoints'], 8641)
        self.assertEqual(len(p['targets']), 1)
        self.assertEqual(p['targets'][0]['legendFormat'], '{{state}}')
        self.assertIn('count_values(', p['targets'][0]['expr'])
        for t in p['targets']:
            self.assertTrue(t['range'])
            self.assertFalse(t['instant'])
            self.assertEqual(t['interval'], '15s')
            self.assertIn('name!="root"', t['expr'])
            self.assertNotIn('argocd_app_sync_total', t['expr'])
            self.assertNotIn('topk', t['expr'])
        self.assertTrue(p['options']['legend']['showLegend'])
        self.assertEqual(p['options']['tooltip']['mode'], 'all')
        custom = p['fieldConfig']['defaults']['custom']
        self.assertGreater(custom['fillOpacity'], 0)
        self.assertEqual(custom['stacking']['mode'], 'normal')
        self.assertEqual(custom['lineInterpolation'], 'stepAfter')
        self.assertFalse(custom['spanNulls'])
        self.assertEqual(len(p['fieldConfig']['overrides']), 5)

    @unittest.skipUnless(shutil.which('helm'), 'helm needed for apply-size regression')
    def test_rendered_apply_annotation_stays_below_kubernetes_limit(self):
        import yaml
        chart = ROOT / 'charts/monitoring-k3s'
        rendered = subprocess.check_output(['helm', 'template', 'monitoring-k3s', str(chart),
                    '-n', 'cattle-monitoring-system', '-f', str(chart / 'alert-graphs.values.yaml')], text=True)
        cm = next(x for x in yaml.safe_load_all(rendered) if x and x.get('metadata', {}).get('name') == 'socrat-traffic-light-tmp-lab-dashboard')
        self.assertLess(len(json.dumps(cm, separators=(',', ':')).encode()), 240000)
        self.assertEqual(json.loads(next(iter(cm['data'].values()))), self.dashboard)

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
    def test_promql_partition_latest_labels_and_telemetry_gaps(self):
        def series(name, values='1+0x120'):
            return {'series': name, 'values': values}
        def app(name, health='Healthy', sync='Synced', values='1+0x120'):
            return series(f'argocd_app_info{{job="socrat-argocd",name="{name}",health_status="{health}",sync_status="{sync}"}}', values)
        def checks(counts, when='30m'):
            return [{'expr': expr, 'eval_time': when,
                     'exp_samples': [] if n is None else [{'labels': '{}', 'value': n}]}
                    for (_, expr, _), n in zip(lab.queries()[1], counts)]
        up = series('up{job="socrat-argocd"}')
        mixed = [up, app('a'), app('b', sync='OutOfSync'), app('c', 'Progressing', 'OutOfSync'),
                 app('d', 'Suspended'), app('e', 'Degraded', 'OutOfSync'), app('f', 'Unknown'),
                 app('g', sync='FutureStatus'), app('root', 'Degraded')]
        cases = [
            {'interval': '15s', 'input_series': mixed, 'promql_expr_test': checks([1, 2, 1, 1, 2])},
            {'interval': '15s', 'input_series': [up, app('a')], 'promql_expr_test': checks([1, 0, 0, 0, 0])},
            {'interval': '15s', 'input_series': [], 'promql_expr_test': checks([None]*5)},
            {'interval': '15s', 'input_series': [series(up['series'], '0+0x120'), app('a')],
             'promql_expr_test': checks([None]*5)},
            {'interval': '15s', 'input_series': [up, app('a', values='1')],
             'promql_expr_test': checks([None]*5, '3m')},
            # A fresh healthy app cannot hide a second app with stale telemetry.
            {'interval': '15s', 'input_series': [up, app('a'), app('b', values='1')],
             'promql_expr_test': checks([None]*5, '3m')},
            # The old Healthy label set lingers but the new Degraded one is newer.
            {'interval': '15s', 'input_series': [up, app('a', values='1+0x4'),
                app('a', 'Degraded', 'OutOfSync', values='_ _ _ _ _ 1+0x115')],
             'promql_expr_test': checks([0, 0, 0, 1, 0], '1m30s')},
            # Contradictory same-timestamp label sets still count one app, red wins.
            {'interval': '15s', 'input_series': [up, app('a'), app('a', 'Degraded')],
             'promql_expr_test': checks([0, 0, 0, 1, 0])},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queries.yaml'
            path.write_text(json.dumps({'rule_files': [], 'evaluation_interval': '15s', 'tests': cases}))
            result = subprocess.run(['promtool', 'test', 'rules', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
