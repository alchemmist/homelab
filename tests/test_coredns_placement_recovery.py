"""Safety contracts for the scoped CoreDNS availability recovery."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_future_dns_placement_uses_two_sites_without_nl_dependency():
    d=yaml.safe_load((ROOT/'ansible/roles/k3s_ha_dependencies/defaults/main.yml').read_text())
    assert d['k3s_ha_dependencies_coredns_nodes']==['socrat-0','socrat-3']


def test_recovery_has_bounded_writers_and_stops_on_partial_failure():
    plays=yaml.safe_load((ROOT/'ansible/playbooks/coredns-placement-recovery.yml').read_text())
    assert [p['hosts'] for p in plays]==['socrat-0:socrat-1','socrat-0','socrat-0:socrat-1']
    assert all(p['any_errors_fatal'] for p in plays)
    assert all('StrictHostKeyChecking=yes' in p['vars']['ansible_ssh_common_args'] for p in plays)


def test_plan_requires_spec_cas_backup_and_no_unavailable_dns():
    text=(ROOT/'ansible/playbooks/coredns-placement-recovery.yml').read_text()
    assert "'path':'/spec','value':before.spec" in text
    assert "'path':'/metadata/uid','value':before.metadata.uid" in text
    assert "'maxUnavailable':0" in text
    assert "not receipt.stat.exists" in text
    assert 'expected_preimage' in text and 'STOP: staged drift' in text
    assert 'before.yaml' in text and 'os.replace(new,old)' in text


def test_recovery_does_not_touch_app_or_node_lifecycle():
    plays=yaml.safe_load((ROOT/'ansible/playbooks/coredns-placement-recovery.yml').read_text())
    for p in plays:
        for t in p['tasks']:
            assert 'ansible.builtin.systemd' not in t
            assert 'ansible.builtin.service' not in t
            assert 'ansible.builtin.include_role' not in t
    text=(ROOT/'ansible/playbooks/coredns-placement-recovery.yml').read_text()
    assert 'flush ruleset' not in text and 'iptables -F' not in text
    assert 'disable-network-policy' not in text
