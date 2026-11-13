import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('udp_probe',ROOT/'scripts/vpn-home-nl-udp-probe.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_only_small_exact_shape_from_home_gets_echoed():
    valid=m.PREFIX+b'x'*16
    assert m.valid(valid,(m.HOME,51843))
    assert not m.valid(valid,('91.189.82.238',51843))
    assert not m.valid(valid+b'x',(m.HOME,51843))
    assert not m.valid(b'bad'+b'x'*100,(m.HOME,51843))

def test_bounded_no_reuse_or_network_state_mutation():
    s=(ROOT/'scripts/vpn-home-nl-udp-probe.py').read_text()
    assert '1<=timeout<=45' in s
    assert 's.sendto(data,peer)' in s
    assert 'setsockopt' not in s
    for forbidden in ['subprocess','wg set','nft','iptables','sudo']:
        assert forbidden not in s
