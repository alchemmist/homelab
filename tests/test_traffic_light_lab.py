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

    def test_every_original_panel_except_argo_is_preserved_verbatim(self):
        original = json.loads(lab.SOURCE.read_text())
        for p in original['panels']:
            if p['id'] != 909:
                self.assertEqual(self.panels[p['id']], p)
        self.assertNotIn(909, self.panels)

    def test_native_only_and_nonoverlapping_tv_grid(self):
        occupied = {}
        for p in self.dashboard['panels']:
            self.assertIn(p['type'], ('stat', 'bargauge', 'table', 'timeseries'))
            g = p['gridPos']
            self.assertLessEqual(g['x'] + g['w'], 24)
            self.assertLessEqual(g['y'] + g['h'], 16)
            for x in range(g['x'], g['x'] + g['w']):
                for y in range(g['y'], g['y'] + g['h']):
                    self.assertNotIn((x, y), occupied)
                    occupied[x, y] = p['id']
        self.assertEqual(len(self.panels), len(self.dashboard['panels']))

    def test_no_key_identifiers_or_auto_public_share(self):
        for pid in range(950, 961):
            content = json.dumps(self.panels[pid])
            for private_label in ('hashed_api_key', 'user_email', 'client_ip'):
                self.assertNotIn(private_label, content)
        self.assertNotIn('publicDashboard', self.dashboard)
        self.assertEqual(self.panels[954]['options']['namePlacement'], 'top')

    def test_readiness_is_honest_and_spend_is_coverage_gated(self):
        for pid in (957, 958, 959):
            p = self.panels[pid]
            self.assertIn('Deployment readiness only', p['description'])
            self.assertIn('timestamp(', p['targets'][0]['expr'])
            self.assertIn('vector(-2)', p['targets'][0]['expr'])
        self.assertIn('count(litellm_spend_capture_rate)', self.panels[955]['targets'][0]['expr'])
        self.assertEqual(self.panels[955]['fieldConfig']['defaults']['noValue'], 'Unverified')

    @unittest.skipUnless(shutil.which('promtool'), 'promtool is needed for PromQL semantics')
    def test_promql_healthy_problem_missing_stale_scaled_off_and_unpriced(self):
        def series(name, values='1+0x3'):
            return {'series': name, 'values': values}

        up = series('up{job="socrat-argocd"}')
        healthy = series('argocd_app_info{job="socrat-argocd",name="a",health_status="Healthy",sync_status="Synced"}')
        drift = series('argocd_app_info{job="socrat-argocd",name="b",health_status="Healthy",sync_status="OutOfSync"}')
        down = series('argocd_app_info{job="socrat-argocd",name="c",health_status="Degraded",sync_status="Synced"}')
        def check(pid, value, when='2m'):
            return {'expr': self.panels[pid]['targets'][0]['expr'], 'eval_time': when,
                    'exp_samples': [] if value is None else [{'labels': '{}', 'value': value}]}
        cases = [
            {'interval': '1m', 'input_series': [up, healthy, drift, down],
             'promql_expr_test': [check(950, 1), check(951, 1), check(952, 1)]},
            {'interval': '1m', 'input_series': [up, healthy],
             'promql_expr_test': [check(950, 1), check(951, 0), check(952, 0)]},
            {'interval': '1m', 'input_series': [],
             'promql_expr_test': [check(950, None), check(951, None), check(952, None), check(957, -2), check(955, None)]},
            {'interval': '1m', 'input_series': [series(up['series'], '1'), series(healthy['series'], '1')],
             'promql_expr_test': [check(950, None, '3m'), check(951, None, '3m')]},
        ]
        available = 'kube_deployment_status_replicas_available{namespace="rustfs",deployment="rustfs"}'
        desired = 'kube_deployment_spec_replicas{namespace="rustfs",deployment="rustfs"}'
        for a, n, expect in [(1, 1, 0), (0, 1, 1), (0, 0, 1)]:
            cases.append({'interval': '1m', 'input_series': [series(available, f'{a}+0x3'), series(desired, f'{n}+0x3')],
                          'promql_expr_test': [check(957, expect)]})
        for coverage, expect in [('NaN NaN NaN', None), ('1+0x3', 0), ('0+0x3', None)]:
            cases.append({'interval': '1m', 'input_series': [series('up{job="litellm"}'),
                          series('litellm_spend_metric_total{api_key_alias="test"}', '0+0x3'),
                          series('litellm_spend_capture_rate{api_provider="a"}', coverage)],
                          'promql_expr_test': [check(955, expect)]})
        # A valid provider must not conceal another provider's NaN coverage.
        cases.append({'interval': '1m', 'input_series': [series('up{job="litellm"}'),
                      series('litellm_spend_metric_total', '0+0x3'),
                      series('litellm_spend_capture_rate{api_provider="a"}'),
                      series('litellm_spend_capture_rate{api_provider="b"}', 'NaN NaN NaN')],
                      'promql_expr_test': [check(955, None)]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queries.yaml'
            path.write_text(json.dumps({'rule_files': [], 'evaluation_interval': '1m', 'tests': cases}))
            result = subprocess.run(['promtool', 'test', 'rules', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
