from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / 'ansible/playbooks/otel-socrat4-cpu-tuning.yml'


def test_override_only_changes_parallelism():
    text = (ROOT / 'ansible/files/otel/socrat4-cpu.conf').read_text()
    active = [x for x in text.splitlines() if x and not x.startswith('#')]
    assert active == ['[Service]', 'Environment=GOMAXPROCS=1']


def test_scoped_play_stops_on_drift_and_preserves_configuration():
    play = yaml.safe_load(PLAY.read_text())[0]
    assert play['hosts'] == 'socrat-4' and play['any_errors_fatal']
    assert 'StrictHostKeyChecking=yes' in play['vars']['ansible_ssh_common_args']
    assert len(play['vars']['protected_files']) == 3
    assert 'not old_override.stat.exists' in PLAY.read_text()
    assert 'postimages' in PLAY.read_text()


def test_only_telemetry_is_restarted_and_rollback_exists():
    p = yaml.safe_load(PLAY.read_text())[0]
    activation = next(t for t in p['tasks'] if 'block' in t)
    for tasks in [activation['block'], activation['rescue']]:
        services = [t['ansible.builtin.systemd_service'] for t in tasks if 'ansible.builtin.systemd_service' in t]
        assert len(services) == 1
        assert services[0]['name'] == 'homelab-otel-agent.service'
    assert activation['rescue'][0]['ansible.builtin.file']['state'] == 'absent'
    assert activation['block'][1]['ansible.builtin.uri']['status_code'] == 200


def test_production_owner_preserves_the_same_moscow_only_override():
    p = yaml.safe_load((ROOT/'ansible/playbooks/otel-production-agents.yml').read_text())[0]
    t = next(t for t in p['tasks'] if t.get('name') == 'Install Moscow-only Collector parallelism override')
    assert t['when'] == "inventory_hostname == 'socrat-4'"
    assert t['ansible.builtin.copy']['src'].endswith('/../files/otel/socrat4-cpu.conf')
    assert t['notify'] == 'Restart validated host agent'
