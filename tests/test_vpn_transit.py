"""Static safety contracts for the narrowly scoped Moscow transit deployment."""
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_fixed_destinations_and_public_backend_protection():
    config = json.loads((ROOT / 'deploy/vpn-hardening/moscow-transit.json').read_text())
    assert config['outbounds'] == [{'tag': 'fixed-destination', 'protocol': 'freedom'}]
    ports = set()
    for inbound in config['inbounds']:
        assert inbound['protocol'] == 'tunnel'
        assert inbound['settings']['followRedirect'] is False
        assert not inbound.get('sniffing', {}).get('enabled', False)
        ports.update(int(p) for p in str(inbound['port']).split(','))
        if inbound['tag'].startswith('vpn-'):
            assert inbound['settings']['rewriteAddress'] == '10.251.4.2'
            assert 'rewritePort' not in inbound['settings']
        else:
            assert inbound['tag'] in {'management-wg-relay', 'management-wg-tcp-relay'}
            assert inbound['settings']['rewriteAddress'] == '109.120.141.60'
            assert inbound['settings']['rewritePort'] in {51830, 51840}
    assert not ports & {22, 2222, 12096, 18082, 32063, 32087}
    assert ports == {80, 443, 32053, 32083, 32084, 32085, 32086, 51832, 51840}


def test_transport_never_advertises_a_default_route_or_mutates_old_interface():
    template = (ROOT / 'ansible/roles/vpn_transit/templates/wg-vpn-transit.conf.j2').read_text()
    assert '0.0.0.0/0' not in template
    assert '::/0' not in template
    assert '10.251.4.2/32' in template and '10.251.4.1/32' in template
    play = yaml.safe_load((ROOT / 'ansible/playbooks/vpn-transit-transport.yml').read_text())
    assert play[0]['hosts'] == 'socrat-2:socrat-4'
    tasks = (ROOT / 'ansible/roles/vpn_transit/tasks/main.yml').read_text()
    assert 'wg-socrat' not in tasks
    assert 'wg-quick@wg-vpn-transit' in tasks


def test_small_worker_keeps_admission_and_has_no_control_plane_role():
    values = yaml.safe_load((ROOT / 'ansible/inventory/host_vars/socrat-4.yml').read_text())
    assert values['k3s_worker_profile'] == 'transit-worker'
    assert values['k3s_worker_bootstrap_taint'].endswith(':NoSchedule')
    play = yaml.safe_load((ROOT / 'ansible/playbooks/k3s-transit-worker.yml').read_text())
    assert play[0]['hosts'] == 'socrat-4'
    assert play[0]['roles'] == ['k3s_worker']


def test_public_key_inventory_has_no_private_material():
    values = yaml.safe_load((ROOT / 'ansible/vars/vpn-transit.yml').read_text())
    assert len(values['vpn_transit_public_keys']) == 5
    assert all(set(keys) <= {'wg-vpn-transit', 'wg-vps-gateway'} for keys in values['vpn_transit_public_keys'].values())
    assert values['vpn_transit_port'] == 51841
    assert len(values['vpn_transit_xray_sha256']) == 64
