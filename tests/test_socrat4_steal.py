"""Native PromQL regression for owner-approved socrat-4 CPU steal exception."""
import copy
import subprocess
import tempfile
from pathlib import Path
import yaml


def test_socrat4_steal():
    rendered = subprocess.check_output(['helm', 'template', 'monitoring', 'charts/monitoring-k3s'], text=True)
    groups = [g for d in yaml.safe_load_all(rendered) if d and d['kind'] == 'PrometheusRule' for g in d['spec']['groups']]
    group = next(g for g in groups if g['name'] == 'socrat.nodes.hardware')
    rules = [r for r in group['rules'] if r.get('alert') == 'SocratNodeCPUStealHigh']
    assert len(rules) == 2
    tests = []
    for node, value, duration, firing in [
        ('socrat-4', .20, 60, False),
        ('socrat-4', .30, 60, False),
        ('socrat-4', .35, 29, False),
        ('socrat-4', .35, 31, True),
        ('socrat-0', .15, 14, False),
        ('socrat-0', .15, 16, True),
    ]:
        rule = rules[1] if node == 'socrat-4' else rules[0]
        annotations = {k: v.replace('{{ $labels.node }}', node) for k,v in rule['annotations'].items()}
        tests.append({'name': f'{node}-{value}-{duration}', 'interval': '1m',
            'input_series': [{'series': f'socrat:node_cpu_steal:ratio5m{{node="{node}"}}', 'values': f'{value}x65'}],
            'alert_rule_test': [{'eval_time': f'{duration}m', 'alertname': rule['alert'], 'exp_alerts': [{'exp_labels': {'node': node, 'severity': 'warning'}, 'exp_annotations': annotations}] if firing else []}]})
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p/'rules.yml').write_text(yaml.safe_dump({'groups': [{'name': 'psi', 'rules': rules}]}))
        (p/'test.yml').write_text(yaml.safe_dump({'rule_files': ['rules.yml'], 'evaluation_interval': '1m', 'tests': tests}))
        subprocess.run(['promtool', 'test', 'rules', 'test.yml'], cwd=p, check=True)
        (p/'node-hardware.rules.yml').write_text(yaml.safe_dump({'groups': [group]}))
        (p/'old.yml').write_text(Path('tests/node-hardware.test.yml').read_text())
        subprocess.run(['promtool', 'test', 'rules', 'old.yml'], cwd=p, check=True)


if __name__ == '__main__':
    test_socrat4_steal()
