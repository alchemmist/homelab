from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]

def test_default_prepares_without_activating_and_has_explicit_acceptance():
 p=yaml.safe_load((ROOT/'ansible/playbooks/moscow-native-primary.yml').read_text())[0]
 assert p['hosts']=='socrat-4' and p['any_errors_fatal']
 assert 'default("preflight")' in p['vars']['phase']
 text=(ROOT/'ansible/playbooks/moscow-native-primary.yml').read_text()
 assert 'moscow_native_data_path_accepted' in text
 assert 'spec.nodeName=socrat-4' in text and 'protected' not in p['hosts']
 acts=[t for t in p['tasks'] if t.get('ansible.builtin.command','')=='python3 /usr/local/libexec/vpn-transit-failover.py activate']
 assert len(acts)==1 and acts[0]['when']=="phase == 'activate'"
 assert 'state: absent' not in text and 'k3s-uninstall' not in text

def test_enrollment_cannot_release_native_fence():
 p=yaml.safe_load((ROOT/'ansible/playbooks/k3s-transit-worker.yml').read_text())[0]
 assert any(t.get('ansible.builtin.assert',{}).get('that')=='not native_fence.stat.exists' for t in p['pre_tasks'])
