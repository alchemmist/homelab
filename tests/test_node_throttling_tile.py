import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / 'charts/monitoring-k3s/dashboards/nodes.json'
PROMTOOL = os.environ.get('PROMTOOL') or shutil.which('promtool')


def panel():
    dashboard = json.loads(DASHBOARD.read_text())
    return next(item for item in dashboard['panels'] if item.get('id') == 215)


def fixtures():
    expr = panel()['targets'][0]['expr'].replace('$node', 'socrat-3')
    source = 'up{job="kubelet",metrics_path="/metrics/cadvisor",instance="node:10250"}'
    ksm = 'up{job="kube-state-metrics"}'
    info = 'kube_node_info{job="kube-state-metrics",node="socrat-3"}'
    rules = 'prometheus_rule_group_last_evaluation_timestamp_seconds{rule_group="/rules/file;kubernetes-resources"}'
    quota = 'kube_pod_container_resource_limits{job="kube-state-metrics",node="socrat-3",resource="cpu",namespace="app",pod="app-1",container="app"}'
    periods = 'container_cpu_cfs_periods_total{job="kubelet",metrics_path="/metrics/cadvisor",node="socrat-3",container="app"}'
    healthy = {
        source: '1x12',
        ksm: '1x12',
        info: '1x12',
        rules: '0+30x12',
        'kubelet_node_name{job="kubelet",node="socrat-3",instance="node:10250"}': '1x12',
    }
    cases = [
        ('no CPU quota is not applicable', {}, -1),
        ('running init CPU quota requires CFS telemetry', {quota.replace('kube_pod_container_resource_limits', 'kube_pod_init_container_resource_limits'): '2x12', 'kube_pod_init_container_status_running{job="kube-state-metrics",namespace="app",pod="app-1",container="app"}': '1x12'}, None),
        ('finished init CPU quota does not prevent not applicable', {quota.replace('kube_pod_container_resource_limits', 'kube_pod_init_container_resource_limits'): '2x12', 'kube_pod_init_container_status_running{job="kube-state-metrics",namespace="app",pod="app-1",container="app"}': '0x12'}, -1),
        ('zero CPU quota is not applicable', {quota: '0x12'}, -1),
        ('lingering CFS counters do not make unlimited containers clear', {periods: '0+10x12'}, -1),
        ('quota and CFS counters are clear', {quota: '2x12', periods: '0+10x12'}, 0),
        ('quota without CFS telemetry is unknown', {quota: '2x12'}, None),
        ('failed cAdvisor is unknown', {source: '0x12'}, None),
        ('missing cAdvisor is unknown', {source: None}, None),
        ('stale cAdvisor is unknown', {source: '1x6 _x6'}, None),
        ('failed kube state metrics is unknown', {ksm: '0x12'}, None),
        ('missing kube state metrics is unknown', {ksm: None}, None),
        ('stale kube state metrics is unknown', {ksm: '1x6 _x6'}, None),
        ('missing selected node inventory is unknown', {info: None}, None),
        ('stale rule evaluation is unknown', {rules: '0x12'}, None),
        ('firing alert takes precedence over not applicable', {'ALERTS{alertname="CPUThrottlingHigh",alertstate="firing",instance="node:10250"}': '1x12'}, 2),
        ('pending alert takes precedence over not applicable', {'ALERTS{alertname="CPUThrottlingHigh",alertstate="pending",instance="node:10250"}': '1x12'}, 1),
        ('another node CPU quota is not applicable here', {quota.replace('socrat-3', 'socrat-0'): '2x12'}, -1),
    ]
    tests = []
    for name, overrides, expected in cases:
        series = healthy | overrides
        tests.append({
            'name': name,
            'interval': '30s',
            'input_series': [{'series': key, 'values': value} for key, value in series.items() if value is not None],
            'promql_expr_test': [{
                'expr': expr,
                'eval_time': '5m',
                'exp_samples': [] if expected is None else [{'labels': '{}', 'value': expected}],
            }],
        })
    return {'rule_files': [], 'evaluation_interval': '30s', 'tests': tests}


class NodeThrottlingTileTest(unittest.TestCase):
    def test_not_applicable_and_no_telemetry_are_distinct(self):
        defaults = panel()['fieldConfig']['defaults']
        mapping = next(item for item in defaults['mappings'] if item['type'] == 'value')
        self.assertEqual(mapping['options']['-1']['text'], 'N/A')
        self.assertEqual(defaults['noValue'], 'No telemetry')
        self.assertIn('positive CPU limit', panel()['description'])

    @unittest.skipUnless(PROMTOOL, 'promtool is not installed; use --generate for remote execution')
    def test_promql_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'node-throttling.test.yml'
            path.write_text(json.dumps(fixtures()))
            subprocess.run([PROMTOOL, 'test', 'rules', str(path)], check=True)


if __name__ == '__main__':
    if '--generate' in sys.argv:
        print(json.dumps(fixtures(), indent=2))
    else:
        unittest.main()
