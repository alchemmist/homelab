import importlib.util,json
from pathlib import Path
from types import SimpleNamespace
import pytest,yaml
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def env(tmp_path,monkeypatch):
 spec=importlib.util.spec_from_file_location('upgrade',ROOT/'scripts/moscow-watchdog-upgrade.py')
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 state=tmp_path/'state';state.mkdir();(state/'state.json').write_text(json.dumps({'mode':'native','healthy':True}));(state/'fallback.active').touch()
 old=b'# old fixture\n';dest=tmp_path/'controller.py';dest.write_bytes(old)
 candidate=tmp_path/'candidate.py';candidate.write_bytes(b'# new fixture\n')
 monkeypatch.setattr(m,'STATE',state);monkeypatch.setattr(m,'ROOT',tmp_path/'receipt');monkeypatch.setattr(m,'DEST',dest);monkeypatch.setattr(m,'OLD',m.sha(old))
 monkeypatch.setattr(m.os,'geteuid',lambda:0);monkeypatch.setattr(m.os,'uname',lambda:SimpleNamespace(nodename='socrat-4'))
 monkeypatch.setattr(m,'unit',lambda name:name=='homelab-vpn-transit-native')
 return m,candidate,dest

def test_exact_atomic_upgrade_keeps_fence_and_state(env):
 m,candidate,dest=env;before=(m.STATE/'state.json').read_bytes()
 m.install(candidate,m.sha(candidate.read_bytes()))
 assert dest.read_bytes()==candidate.read_bytes() and (m.ROOT/'before.py').read_bytes()==b'# old fixture\n'
 assert (m.STATE/'fallback.active').exists() and (m.STATE/'state.json').read_bytes()==before
 assert json.loads((m.ROOT/'accepted.json').read_text())['runtime_changed'] is False
 with pytest.raises(RuntimeError,match='drift'):m.install(candidate,m.sha(candidate.read_bytes()))

def test_conflicting_active_agent_refuses_without_mutation(env,monkeypatch):
 m,candidate,dest=env;monkeypatch.setattr(m,'unit',lambda _:True)
 with pytest.raises(RuntimeError,match='ownership'):m.install(candidate,m.sha(candidate.read_bytes()))
 assert dest.read_bytes()==b'# old fixture\n' and not m.ROOT.exists()

def test_unknown_candidate_refused(env):
 m,candidate,dest=env
 with pytest.raises(RuntimeError,match='SHA'):m.install(candidate,'0'*64)
 assert not m.ROOT.exists()

def test_repair_is_separate_explicit_phases_and_keeps_membership():
 source=(ROOT/'ansible/playbooks/moscow-watchdog-repair.yml').read_text();yaml.safe_load(source)
 assert 'moscow_watchdog_repair_confirmed' in source and 'default("preflight")' in source
 assert "phase == 'return'" in source and 'controller.stat.checksum == new_sha' in source
 assert 'failback' in source and 'kubectl delete' not in source and 'wg-quick' not in source


def test_voter_json_items_is_key_not_dict_method():
 source=(ROOT/'ansible/playbooks/moscow-watchdog-repair.yml').read_text()
 assert '(voters.stdout | from_json)["items"]' in source
 assert '(voters.stdout | from_json).items' not in source
