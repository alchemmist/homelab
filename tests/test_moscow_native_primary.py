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


def runtime_module():
 import importlib.util
 s=importlib.util.spec_from_file_location('retire',ROOT/'scripts/moscow-retire-worker-runtime.py')
 m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def test_runtime_refuses_unknown_workloads_and_pvc():
 import pytest
 m=runtime_module()
 def pod(ns,name,uid):
  return {'metadata':{'namespace':ns,'name':name,'uid':uid},'spec':{'nodeName':'socrat-4'},'status':{}}
 good={'items':[pod('vpn-transit','vpn-transit-a','a'),pod('cattle-monitoring-system','kube-prometheus-stack-prometheus-node-exporter-b','b')]}
 assert len(m.allowed(good)[0])==2
 good['items'][0]['spec']['volumes']=[{'persistentVolumeClaim':{'claimName':'do-not-delete'}}]
 with pytest.raises(AssertionError):m.allowed(good)
 with pytest.raises(AssertionError):m.allowed({'items':[]})


def test_retirement_requires_gitops_zero_and_uid_precondition():
 text=(ROOT/'ansible/playbooks/moscow-retire-worker.yml').read_text()
 p=yaml.safe_load(text)[0]
 assert p['hosts']=='socrat-4' and p['any_errors_fatal']
 assert 'spec.replicas == 0' in text and 'preconditions' in text and 'old_node_uid' in text
 assert 'moscow_native_data_path_accepted' in text and 'moscow_retire_worker_confirm' in text
 assert 'k3s-killall' not in text and 'k3s-uninstall' not in text
 assert 'enabled: false' in text and 'state: absent' not in text
