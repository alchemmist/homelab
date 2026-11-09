"""Real PromQL tests: power warnings precede automatic sleep; missing voters stay visible."""
import copy
import shutil
import subprocess
from pathlib import Path
import pytest
import yaml
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which('helm') or not shutil.which('promtool'), reason='Native Helm/promtool required')
def test_power_and_quorum_with_native_promtool(tmp_path):
    rendered = subprocess.check_output(['helm', 'template', 'monitoring', str(ROOT/'charts/monitoring-k3s')], text=True)
    resource = next(x for x in yaml.safe_load_all(rendered) if x and x.get('metadata', {}).get('name') == 'socrat-control-plane-safety')
    group = resource['spec']['groups'][0]
    rules = {r['alert']: r for r in group['rules']}
    assert len(rules) == 4
    assert rules['SocratControlPlaneOnBattery']['for'] == '2m'
    assert rules['SocratControlPlaneBatteryLow']['for'] == '2m'
    assert rules['SocratEtcdVoterHealthUnavailable']['for'] == '1m'
    assert rules['SocratEtcdQuorumHealthUnproven']['for'] == '30s'
    (tmp_path/'rules.yaml').write_text(yaml.safe_dump({'groups': [group]}))
    def fixture(name, online=1, capacity=88, voters=3, fire=(), missing=False, stale=False):
        series = [] if missing else [
            {'series': 'node_power_supply_online{instance="node1:9100",power_supply="ACAD"}', 'values': f'{online}x20'},
            {'series': 'node_power_supply_capacity{instance="node1:9100",power_supply="BATT"}', 'values': f'{capacity}x20'},
            {'series': 'node_uname_info{instance="node1:9100",nodename="socrat-1"}', 'values': '1x20'},
        ]
        for n in range(voters):
            series.append({'series': f'etcd_server_has_leader{{job="kube-etcd",node="socrat-{n}"}}', 'values': '1x20' if not stale or n != 2 else '1 1 1 1 1 _ _ _ _ _ _'})
        checks = []
        for alert, rule in rules.items():
            expected = []
            if alert in fire:
                labels = copy.deepcopy(rule['labels'])
                if 'ControlPlane' in alert:
                    labels.update(instance='node1:9100', nodename='socrat-1', node='socrat-1')
                expected = [{'exp_labels': labels, 'exp_annotations': rule['annotations']}]
            checks.append({'eval_time': '5m', 'alertname': alert, 'exp_alerts': expected})
        return {'name': name, 'interval': '30s', 'input_series': series, 'alert_rule_test': checks}
    warning = 'SocratEtcdVoterHealthUnavailable'
    critical = 'SocratEtcdQuorumHealthUnproven'
    tests = [fixture('healthy'), fixture('AC disconnected before battery critical', online=0, fire=('SocratControlPlaneOnBattery',)),
             fixture('weak charger/low battery still matters while AC online', capacity=15, fire=('SocratControlPlaneBatteryLow',)),
             fixture('one voter missing removes failure margin', voters=2, fire=(warning,)),
             fixture('two voters missing', voters=1, fire=(warning,critical)),
             fixture('no health telemetry must not look healthy', missing=True, voters=0, fire=(warning,critical)),
             fixture('stale third voter does not prove health', voters=3, stale=True, fire=(warning,))]
    (tmp_path/'tests.yaml').write_text(yaml.safe_dump({'rule_files': ['rules.yaml'], 'evaluation_interval': '30s', 'tests': tests}))
    run = subprocess.run(['promtool', 'test', 'rules', 'tests.yaml'], cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


def test_agent_native_compaction_keeps_durable_barrier():
    agent = yaml.safe_load((ROOT/'deploy/monitoring/otel/agent.yaml').read_text())
    storage = agent['extensions']['file_storage']
    assert storage['fsync'] is True
    assert storage.get('recreate', False) is False
    assert storage['compaction'] == {'on_start': True, 'on_rebound': True, 'directory': '${env:OTEL_STORAGE_DIR}/agent-compaction'}
    assert agent['exporters']['otlp/logs']['sending_queue']['storage'] == 'file_storage'
    assert agent['exporters']['otlp/logs']['sending_queue']['block_on_overflow'] is True
    assert 'batch' not in agent['service']['pipelines']['logs']['processors']
