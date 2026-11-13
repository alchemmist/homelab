import importlib.util
from pathlib import Path
import pytest,yaml
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('repair',ROOT/'scripts/moscow-api-routes-repair.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def fixture():
 peers={key:[addr+'/32'] for key,addr in zip(m.PEERS,['10.250.0.1','10.250.0.3'])}
 peers['other']=['10.250.0.2/32']
 text='[Interface]\nPrivateKey = fixture-not-a-real-key\nAddress = 10.250.0.40/24\n'
 for key,nets in peers.items():text+='[Peer]\nPublicKey = '+key+'\nAllowedIPs = '+','.join(nets)+'\nPersistentKeepalive = 25\n'
 return text,peers

def test_only_two_allowedip_lines_change_preserving_private_key_and_other_peers():
 text,peers=fixture();new,after=m.candidate(text,peers)
 assert m.project(new)[1]==after and after['other']==peers['other']
 for key,target in m.PEERS.items():assert after[key]==peers[key]+[target]
 assert [l for l in new.splitlines() if not l.startswith('AllowedIPs')]==[l for l in text.splitlines() if not l.startswith('AllowedIPs')]

def test_rejects_runtime_drift_and_conflicting_cryptokey_owner():
 text,peers=fixture();bad=dict(peers);bad['other']=['0.0.0.0/0']
 with pytest.raises(ValueError,match='drift'):m.candidate(text,bad)
 text=text.replace('AllowedIPs = 10.250.0.2/32','AllowedIPs = 0.0.0.0/0')
 with pytest.raises(ValueError,match='another peer'):m.candidate(text,bad)

def test_inventory_keeps_exact_api_host_routes_and_no_default():
 host=yaml.safe_load((ROOT/'ansible/inventory/host_vars/socrat-4.yml').read_text())
 assert host['wg_socrat_extra_allowed_peer_ips']=={'socrat-4':{'socrat-0':['192.168.0.23/32'],'socrat-1':['192.168.0.24/32']}}
 source=(ROOT/'scripts/moscow-api-routes-repair.py').read_text()
 assert "'route','add'" in source and 'wg-quick' not in source
 assert "'systemctl'" not in source and 'private-key' not in source


def test_runtime_parser_retains_every_prefix_with_tabs_spaces_or_commas():
 assert m.allowed_ips('key\t10.0.0.1/32 192.168.0.1/32\n')=={'key':['10.0.0.1/32','192.168.0.1/32']}
 assert m.allowed_ips('key\t10.0.0.1/32,192.168.0.1/32\n')=={'key':['10.0.0.1/32','192.168.0.1/32']}
