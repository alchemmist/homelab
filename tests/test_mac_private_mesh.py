"""Mac SSH must use narrow mesh routes, without SSH bastions or source masking."""
from pathlib import Path
import shlex
import subprocess
import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


def test_four_nodes_have_unique_exact_client_host_routes():
    defaults = load('ansible/roles/wireguard_admin_client/defaults/main.yml')
    peers = defaults['wireguard_admin_peers']
    routes = [route for p in peers for route in p.get('allowed_ips', [p['address'] + '/32'])]
    assert len(peers) == 3
    assert len(routes) == len(set(routes)) == 4
    assert set(routes) == {'10.250.0.1/32', '10.250.0.2/32', '10.250.0.3/32', '10.250.0.5/32'}
    assert '10.250.0.5/32' in peers[0]['allowed_ips']
    assert peers[0]['name'] == 'socrat-0'
    assert 'default' not in routes and '0.0.0.0/0' not in routes


def test_worker_routes_mac_back_to_same_gateway_without_duplicate_peer():
    worker = load('ansible/inventory/host_vars/socrat-3.yml')
    assert '10.250.0.4/32' in worker['wg_socrat_extra_allowed_peer_ips']['socrat-3']['socrat-0']
    assert worker['wg_socrat_admin_clients'] == {}


def render_firewall(rules):
    env = Environment()
    env.filters['quote'] = shlex.quote
    env.filters['bool'] = bool
    env.filters['dict2items'] = lambda d: [{'key': k, 'value': v} for k, v in d.items()]
    defaults = load('ansible/roles/wireguard_admin_firewall/defaults/main.yml')
    defaults.update(wg_socrat_admin_clients={'mac': {'address': '10.250.0.4'}},
                    wg_socrat_nodes={'socrat-0': {'address': '10.250.0.1'}, 'socrat-3': {'address': '10.250.0.5'}},
                    inventory_hostname='socrat-0', wg_socrat_admin_forward_rules=rules)
    template = (ROOT / 'ansible/roles/wireguard_admin_firewall/templates/wg-socrat-admin-firewall.sh.j2').read_text()
    rendered = env.from_string(template).render(**defaults)
    subprocess.run(['sh', '-n'], input=rendered, text=True, check=True, capture_output=True)
    return rendered


def test_mac_only_forwards_worker_ssh_without_snat():
    host = load('ansible/inventory/host_vars/socrat-0.yml')
    rule = next(r for r in host['wg_socrat_admin_forward_rules'] if r['client'] == 'antonmoss-mac')
    assert rule == {'client': 'antonmoss-mac', 'destination': 'socrat-3', 'tcp_ports': [2222], 'snat': False}
    script = render_firewall([dict(rule, client='mac')])
    assert '-s 10.250.0.4/32 -d 10.250.0.5/32 -p tcp --dport 2222' in script
    assert 'SNAT --to-source' not in script
    assert '-s "$client_address/32" -j REJECT' in script


def test_other_forwarding_rules_keep_legacy_snat_default():
    script = render_firewall([{'client': 'mac', 'destination': 'socrat-3', 'tcp_ports': [2222]}])
    assert 'SNAT --to-source 10.250.0.1' in script


def test_rendered_profile_is_split_and_carries_worker_route():
    env = Environment()
    defaults = load('ansible/roles/wireguard_admin_client/defaults/main.yml')
    defaults.update(wireguard_admin_private_key='offline-private-placeholder')
    defaults['wireguard_admin_peers'] = [dict(p, public_key='offline-public-placeholder') for p in defaults['wireguard_admin_peers']]
    template = (ROOT / 'ansible/roles/wireguard_admin_client/templates/wg-socrat-admin.conf.j2').read_text()
    profile = env.from_string(template).render(**defaults)
    assert 'AllowedIPs = 10.250.0.1/32, 10.250.0.5/32' in profile
    assert 'Endpoint = 109.120.141.97:51830' in profile
    assert '0.0.0.0/0' not in profile
    assert 'DNS =' not in profile
