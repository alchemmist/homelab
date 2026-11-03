#!/usr/bin/env python3
"""Offline compiler: administrative access to existing WireGuard node /32s.

No apply, enrollment, secret creation, WG config/AllowedIPs or host route edits.
Two existing-node NetBird routing peers; never route a host's own WG address
through itself (that would traverse INPUT rather than the routed FORWARD ACL).
"""
import importlib.util
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
ADMIN_GROUP = 'netbird-internal-admins'
NS = 'netbird-host-peers'
NETWORKS = {
    'socrat-0': ('wg-remote-nodes', ('10.250.0.2/32', '10.250.0.3/32', '10.250.0.5/32')),
    'socrat-2': ('wg-home-control-node', ('10.250.0.1/32',)),
}


def peers():
    spec = importlib.util.spec_from_file_location('machine_peers', ROOT/'scripts/netbird-host-peer.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    docs = [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS}}]
    for host in NETWORKS:
        objects = mod.peer(host)
        deployment = objects[1]
        env = deployment['spec']['template']['spec']['containers'][0]['env']
        for e in env:
            if e['name'] == 'NB_DISABLE_SERVER_ROUTES':
                e['value'] = 'false'
        # Keep staged replicas=0; separate guarded activation only after live gates.
        docs.extend(objects)
    return docs


def router_body(peer_id):
    if not isinstance(peer_id, str) or not peer_id:
        raise ValueError('exact enrolled router peer ID required')
    return {'peer': peer_id, 'enabled': True, 'masquerade': True, 'metric': 100}


def resource_body(host, address):
    if host not in NETWORKS or address not in NETWORKS[host][1]:
        raise ValueError('only reviewed remote WG node /32 destinations allowed')
    return {'name': 'wg-node-' + address.split('/')[0].split('.')[-1],
            'description': 'Existing wg-socrat node address; no LAN/pod/service/default routes',
            'address': address, 'enabled': True, 'groups': []}


def policy_body(source_group, resource_id):
    if not source_group or not resource_id or source_group == resource_id:
        raise ValueError('distinct genuine admin JWT group and resource required')
    return {'name': 'admin-wg-' + resource_id, 'enabled': True,
            'description': 'Explicit administrators to one WireGuard node; native SSH/application authorization remains',
            'rules': [{'name': 'admin-to-wg-node', 'enabled': True, 'action': 'accept',
                       'protocol': 'all', 'bidirectional': False, 'sources': [source_group],
                       'destinationResource': {'id': resource_id, 'type': 'host'}}]}


def genuine_admin_group(groups):
    candidates = [g for g in groups if g.get('name') == ADMIN_GROUP]
    if len(candidates) != 1 or candidates[0].get('issued') != 'jwt':
        raise ValueError('real personally refreshed OIDC admin JWT group required; never synthesize API source group')
    if candidates[0].get('resources'):
        raise ValueError('admin source must not contain network resources')
    return candidates[0]['id']


if __name__ == '__main__':
    import sys
    yaml.safe_dump_all(peers(), sys.stdout, sort_keys=False)
