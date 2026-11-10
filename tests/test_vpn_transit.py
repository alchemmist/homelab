"""Static safety contracts for the narrowly scoped Moscow transit deployment."""
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_fixed_destinations_and_public_backend_protection():
    config = json.loads((ROOT / 'deploy/vpn-hardening/moscow-transit.json').read_text())
    management = json.loads((ROOT / 'deploy/vpn-hardening/moscow-management.json').read_text())
    assert config['outbounds'] == [{'tag': 'fixed-destination', 'protocol': 'freedom', 'sendThrough': '10.250.0.40'}]
    ports = set()
    for inbound in config['inbounds'] + management['inbounds']:
        assert inbound['protocol'] == 'tunnel'
        assert inbound['settings']['followRedirect'] is False
        assert not inbound.get('sniffing', {}).get('enabled', False)
        ports.update(int(p) for p in str(inbound['port']).split(','))
        if inbound['tag'].startswith('vpn-'):
            assert inbound['settings']['rewriteAddress'] == '10.250.0.2'
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


def test_home_egress_has_only_known_exact_destination_and_no_default_route():
    import importlib.util
    path=ROOT/'scripts/vpn-home-transit-egress.py'
    spec=importlib.util.spec_from_file_location('home_egress',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    rules=mod.rules()
    assert '0.0.0.0/0' not in rules and 'flush' not in rules
    assert rules.count('ip daddr 109.120.141.60')==10
    assert 'dnat ip to 10.250.0.40:53' in rules
    assert 'dnat ip to 91.189.82.238:51832' in rules
    assert 'masquerade' in rules
    assert '3478' not in rules  # Do not pretend STUN NAT traversal has been validated.
    play=yaml.safe_load((ROOT/'ansible/playbooks/vpn-transit-home-egress.yml').read_text())
    assert play[0]['hosts']=='socrat-0:socrat-1:socrat-3'
    assert play[0]['serial']==1
    source=path.read_text()
    assert 'prohibit' in source and "'32760'" in source
    assert "'default_routes_unchanged': True" in source


def test_exit_fence_never_blocks_shared_https_or_dns():
    import importlib.util
    spec=importlib.util.spec_from_file_location('exit_fence',ROOT/'scripts/vpn-exit-transit-fence.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    assert '{ 32053, 32083, 32084 }' in mod.RULES
    assert '{ 32085, 32086 }' in mod.RULES
    assert '443' not in mod.RULES and '12096' not in mod.RULES and 'flush' not in mod.RULES
    assert 'iifname "eth0"' in mod.RULES


def test_private_authoritative_listener_and_tcp_certificate_identity_preserved():
    values=yaml.safe_load((ROOT/'ansible/inventory/host_vars/socrat-2.yml').read_text())
    assert values['public_dns_extra_listen']==['10.251.4.2@53']
    assert values['public_dns_transit_listener_enabled'] is True
    client=(ROOT/'ansible/roles/wireguard_tcp_transport/templates/client.yaml.j2').read_text()
    assert 'wg_tcp_client_address | default(wg_tcp_server_address)' in client
    assert 'serverName: wg-transport.socrat.internal' in client
    assert 'secure: true' in client


def test_native_recovery_gate_keeps_real_loopback_health_and_subscription_routes():
    from jinja2 import Environment
    edge=yaml.safe_load((ROOT/'charts/traefik-edge/values.yaml').read_text())
    rendered=Environment().from_string((ROOT/'ansible/roles/vpn_failover/templates/Caddyfile.j2').read_text()).render(vpn_failover_edge=edge)
    assert 'not remote_ip 10.251.4.1/32 10.250.0.40/32 127.0.0.1/32' in rendered
    assert 'respond @trojan_denied "Forbidden" 403' in rendered
    assert 'reverse_proxy @trojan 127.0.0.1:32087' in rendered
    assert 'reverse_proxy @subscriptions 127.0.0.1:12096' in rendered
    edge.pop('vpnTransit')
    legacy=Environment().from_string((ROOT/'ansible/roles/vpn_failover/templates/Caddyfile.j2').read_text()).render(vpn_failover_edge=edge)
    assert '@trojan_denied' not in legacy
