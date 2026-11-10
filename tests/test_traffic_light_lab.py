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
        self.assertEqual(set(self.panels) - {p['id'] for p in original['panels']}, {974})
        self.assertNotIn(909, self.panels)
        self.assertFalse(set(self.panels) & set(range(950, 974)))

    def test_line_chart_all_apps_except_root_without_legend_or_stacking(self):
        p = self.panels[974]
        self.assertEqual(p['type'], 'timeseries')
        self.assertEqual(p['gridPos'], {'x': 12, 'y': 8, 'w': 6, 'h': 7})
        self.assertEqual(p['targets'][0]['legendFormat'], '{{name}}')
        self.assertFalse(p['targets'][0]['instant'])
        self.assertTrue(p['targets'][0]['range'])
        self.assertIn('name!="root"', p['targets'][0]['expr'])
        self.assertIn('phase="Succeeded"', p['targets'][0]['expr'])
        self.assertIn('idelta(', p['targets'][0]['expr'])
        self.assertIn('[45s]', p['targets'][0]['expr'])
        self.assertNotIn('increase(', p['targets'][0]['expr'])
        self.assertEqual(p['title'], '')
        self.assertEqual(p['interval'], '15s')
        self.assertEqual(p['targets'][0]['interval'], '15s')
        self.assertGreaterEqual(p['maxDataPoints'], 8641)
        self.assertNotIn('topk', p['targets'][0]['expr'])
        self.assertFalse(p['options']['legend']['showLegend'])
        custom = p['fieldConfig']['defaults']['custom']
        self.assertEqual(custom['drawStyle'], 'line')
        self.assertEqual(custom['fillOpacity'], 0)
        self.assertEqual(custom['stacking']['mode'], 'none')
        self.assertFalse(custom['spanNulls'])
        overrides = p['fieldConfig']['overrides']
        self.assertEqual(sorted(o['matcher']['options'] for o in overrides), lab.application_names())
        self.assertNotIn('root', lab.application_names())
        self.assertEqual(len({lab.application_color(n) for n in lab.application_names()}), len(lab.application_names()))
        for o in overrides:
            self.assertEqual(o['properties'][0]['value']['fixedColor'], lab.application_color(o['matcher']['options']))

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
    def test_promql_root_retired_failures_quiet_pulse_and_telemetry(self):
        def series(name, values='1+0x120'):
            return {'series': name, 'values': values}
        def app(name):
            return series(f'argocd_app_info{{job="socrat-argocd",name="{name}"}}')
        def counter(name, phase='Succeeded', values='0+1x120'):
            return series(f'argocd_app_sync_total{{job="socrat-argocd",name="{name}",phase="{phase}"}}', values)
        def check(values, when='30m'):
            return {'expr': lab.query(), 'eval_time': when, 'exp_samples': [
                {'labels': '{name="' + name + '"}', 'value': value} for name, value in values.items()]}
        up = series('up{job="socrat-argocd"}')
        cases = [
            {'interval': '15s', 'input_series': [up, app('active'), counter('active'),
                app('quiet'), app('failed'), counter('failed', 'Failed'), app('root'), counter('root'), counter('retired')],
             'promql_expr_test': [check({'active': 1, 'quiet': 0, 'failed': 0})]},
            {'interval': '15s', 'input_series': [], 'promql_expr_test': [check({})]},
            {'interval': '15s', 'input_series': [series(up['series'], '1'), series(app('old')['series'], '1')],
             'promql_expr_test': [check({}, '3m')]},
            {'interval': '15s', 'input_series': [series(up['series'], '0+0x120'), app('quiet')],
             'promql_expr_test': [check({})]},
            {'interval': '15s', 'input_series': [up, app('pulse'), counter('pulse', values='0+0x40 1+0x79')],
             'promql_expr_test': [check({'pulse': 1}, '10m15s'), check({'pulse': 0}, '30m')]},
        ]
        cases.extend([
            {'interval': '15s', 'input_series': [up, app('reset'), counter('reset', values='10+0x40 2+0x79')],
             'promql_expr_test': [check({'reset': 2}, '10m15s'), check({'reset': 0}, '10m30s')]},
            {'interval': '15s', 'input_series': [up, app('gap'), counter('gap', values='1')],
             'promql_expr_test': [check({}, '1m')]},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queries.yaml'
            path.write_text(json.dumps({'rule_files': [], 'evaluation_interval': '15s', 'tests': cases}))
            result = subprocess.run(['promtool', 'test', 'rules', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
