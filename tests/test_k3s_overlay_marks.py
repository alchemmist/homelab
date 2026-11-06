import importlib.util
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('overlay_marks', ROOT / 'scripts/k3s-overlay-marks.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def test_scope_and_atomic_replacement():
    s = m.rules('flannel.1', '10.42.0.0/16', True)
    assert s.startswith('delete table inet homelab_k3s_overlay_marks\n')
    assert 'flush ruleset' not in s
    assert 'iifname "flannel.1" ip saddr 10.42.0.0/16 ip daddr 10.42.0.0/16 meta mark != 0 counter meta mark set 0' in s
    assert 'priority -175' in s
    assert 'nb-host' not in s and 'wg-socrat' not in s

@pytest.mark.parametrize('interface,cidr', [('x"; flush ruleset','10.42.0.0/16'),('flannel.1','0.0.0.0/0'),('flannel.1','109.120.141.0/24'),('flannel.1','10.0.0.0/8')])
def test_reject_broad_or_injected_scope(interface, cidr):
    with pytest.raises(ValueError): m.rules(interface, cidr, False)

def test_state_normalization_ignores_only_runtime_fields():
    assert m.normalize({'nftables':[{'metainfo':{}},{'rule':{'handle':3,'expr':[{'counter':{'packets':8,'bytes':200}}]}}]}) == [{'rule':{'expr':[{'counter':{}}]}}]
    expected = m.normalize({'nftables':m.desired('flannel.1','10.42.0.0/16')})
    assert m.normalize({'nftables':expected}) == expected
    assert m.normalize({'nftables':expected+[{'rule':{'expr':[]}}]}) != expected

def test_persistence_has_no_network_restart():
    role = (ROOT/'ansible/roles/k3s_overlay_marks/tasks/main.yml').read_text()
    unit = (ROOT/'ansible/roles/k3s_overlay_marks/templates/overlay-marks.service.j2').read_text()
    assert 'name: homelab-k3s-overlay-marks.service' in role
    assert 'Before=k3s.service k3s-agent.service' in unit
    assert 'wg-quick' not in unit and 'netbird' not in unit
    assert 'k3s_overlay_marks_apply | default(false)' in (ROOT/'ansible/playbooks/k3s-overlay-marks.yml').read_text()


def test_old_nft_table_comment_is_not_a_false_drift_or_ownership_bypass():
    new = {'nftables':m.desired('flannel.1','10.42.0.0/16')}
    old = __import__('copy').deepcopy(new)
    old['nftables'][0]['table'].pop('comment')
    assert m.normalize(old) == m.normalize(new)
    assert not m.owned(old)
    assert m.owned(old, f'table inet {m.TABLE} {{\n\tcomment "{m.OWNER}"\n}}')
    assert not m.owned(old, f'table inet {m.TABLE} {{\n chain foreign {{ comment "{m.OWNER}" }}\n}}')
    old['nftables'][0]['table']['comment']='foreign'
    assert not m.owned(old, f'table inet {m.TABLE} {{\n comment "{m.OWNER}"\n}}')

def test_proven_collision_and_clean_boundary():
    netbird_reverse_mark=0x1bd22
    assert netbird_reverse_mark & 0x10000  # kube-router allow bit
    assert netbird_reverse_mark & 0x2000  # CNI hostport masquerade bit
    assert not (0 & (0x10000 | 0x2000))

def test_default_cli_is_read_only(monkeypatch, capsys):
    import json
    from types import SimpleNamespace
    calls=[]
    def fake(*args, **kwargs):
        calls.append(args)
        if args == ('nft','-j','list','tables'):
            return SimpleNamespace(stdout=json.dumps({'nftables':[]}))
        assert args == ('nft','--check','-f','-')
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(m,'run',fake)
    monkeypatch.setattr(m.os,'umask',lambda _:0)
    monkeypatch.setattr(__import__('sys'),'argv',['helper'])
    m.main()
    assert json.loads(capsys.readouterr().out)['changed'] is False
    assert len(calls)==2


def test_cli_rejects_foreign_table_before_kernel_write(monkeypatch):
    import json,sys
    from types import SimpleNamespace
    def fake(*args, **kwargs):
        if args == ('nft','-j','list','tables'):
            return SimpleNamespace(stdout=json.dumps({'nftables':[{'table':{'family':'inet','name':m.TABLE}}]}))
        if args == ('nft','-j','list','table','inet',m.TABLE):
            return SimpleNamespace(stdout=json.dumps({'nftables':[{'table':{'name':m.TABLE,'comment':'foreign'}}]}))
        assert args == ('nft','-s','list','table','inet',m.TABLE)
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(m,'run',fake)
    monkeypatch.setattr(m.os,'umask',lambda _:0)
    monkeypatch.setattr(sys,'argv',['helper','--apply'])
    with pytest.raises(RuntimeError,match='foreign table'):m.main()
