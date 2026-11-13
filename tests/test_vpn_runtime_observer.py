import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runtime_observer',ROOT/'scripts/vpn-runtime-observer.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_relay_latch_is_not_sufficient_and_split_brain_unknown():
    p=m.PROFILES['socrat-4']
    def state(mode,agent,native,marker):return {'mode':mode,'agent_active':agent,'native_active':native,'fallback_marker':marker}
    assert m.classify(p,state('kubernetes',True,False,False),True,[False],False)==0
    assert m.classify(p,state('native',False,True,True),False,[True],True)==1
    assert m.classify(p,state('native',True,True,True),True,[True],True)==-1
    assert m.classify(p,state('native',False,False,True),False,[False],True)==-1
    assert m.classify(p,state('kubernetes',True,False,False),False,[False],False)==-1
    assert m.classify(p,state('transition-to-native',False,False,True),False,[False],True)==-1

def test_backend_requires_native_both_units_and_server_ownership():
    p=m.PROFILES['socrat-2']
    assert m.classify(p,{'mode':'kubernetes'},True,[False,False],False)==0
    assert m.classify(p,{'mode':'fallback'},False,[True,True],True)==1
    assert m.classify(p,{'mode':'fallback'},False,[True,False],True)==-1
    assert m.classify(p,{'mode':'fallback'},True,[True,True],True)==-1

def test_socket_observation_does_not_call_established_sessions_off(tmp_path):
    net=tmp_path/'net';net.mkdir()
    for name in ['tcp','tcp6','udp','udp6']:(net/name).write_text('header\n')
    (net/'tcp').write_text('header\n0: 00000000:7D35 00000000:0000 01\n')
    assert m.listening(tmp_path,'tcp')=={32053}
    (net/'udp6').write_text('header\n0: 00000000:7D55 00000000:0000 07\n')
    assert m.listening(tmp_path,'udp')=={32085}

def test_export_is_atomic_numeric_no_accounts_or_paths(tmp_path):
    p=tmp_path/'vpn-runtime.prom'
    m.write_metrics(p,'relay',{'runtime':0,'check_success':1,'off':0,'observation_success':1,'observed_timestamp_seconds':123})
    text=p.read_text();assert 'runtime{component="relay"} 0' in text
    assert p.stat().st_mode&0o777==0o644
    assert len(list(tmp_path.iterdir()))==1
    assert 'email' not in text and 'token' not in text

def test_observer_has_no_recovery_or_mutating_command():
    s=(ROOT/'scripts/vpn-runtime-observer.py').read_text()
    for forbidden in ["'tick'","'activate'","'failback'","'demote'","'start'","'stop'","'restart'","'kubectl'","'nft'"]:
        assert forbidden not in s
