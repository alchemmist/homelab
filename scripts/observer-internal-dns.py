#!/usr/bin/env python3
"""Scoped Authentik cluster DNS repair; default read-only, CAS apply once, no replay.

Run on approved controller with root k3s kubectl. A new private state directory is
mandatory for apply. Existing exact owned key is accepted read-only; different key
contents stop. Uncertain writes require inspect/readback, never apply replay.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

HOST = 'auth.socrat.alchemmist.xyz'
KEY = 'authentik-internal.server'
INTERNAL_VIP = '192.168.0.250'


def zone(address):
    import ipaddress
    if not ipaddress.ip_address(address).is_private or ':' in address:
        raise ValueError('Expected private IPv4 Service address')
    return f'''{HOST}:53 {{
    errors
    hosts {{
        {address} {HOST}
        ttl 30
        no_reverse
        fallthrough
    }}
    cache 30
    forward . /etc/resolv.conf
}}
'''


def desired(before, address, owned_value=None):
    value = zone(address)
    old = before.get('data', {}).get(KEY)
    if old is not None and old != value and old != owned_value:
        raise RuntimeError('Owned DNS key collision; inspect before changing')
    data = dict(before.get('data', {})); data[KEY] = value
    return data


def patch(before, data):
    return [
        {'op': 'test', 'path': '/metadata/uid', 'value': before['metadata']['uid']},
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': before['metadata']['resourceVersion']},
        {'op': 'test', 'path': '/data', 'value': before['data']},
        {'op': 'add', 'path': '/data/' + KEY, 'value': data[KEY]},
    ]


def kubectl(*args, payload=None):
    r = subprocess.run(['k3s', 'kubectl', *args], input=payload, capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError('Kubernetes operation failed; inspect private state, no blind retry')
    return json.loads(r.stdout)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--state', type=Path)
    p.add_argument('--approve-sha256')
    p.add_argument('--replace-owned-state', type=Path, help='Prior accepted private receipt authorizing replacement of ONLY its exact owned key')
    a = p.parse_args()
    service = kubectl('-n', 'kube-system', 'get', 'svc', 'traefik', '-o', 'json')
    assert any(x['port'] == 443 for x in service['spec']['ports'])
    cert = kubectl('-n', 'cert-manager', 'get', 'deployment', 'cert-manager', '-o', 'json')
    assert any(x == '--acme-http01-solver-nameservers=1.1.1.1:53,9.9.9.9:53' for c in cert['spec']['template']['spec']['containers'] for x in c.get('args', [])), 'Public ACME resolver precondition missing'
    before = kubectl('-n', 'kube-system', 'get', 'configmap', 'coredns-custom', '-o', 'json')
    assert before.get('data') and not before.get('immutable', False)
    address = INTERNAL_VIP
    owned_value = None
    if a.replace_owned_state:
        receipt = json.loads((a.replace_owned_state / 'receipt.json').read_text())
        previous = json.loads((a.replace_owned_state / 'after.json').read_text())
        assert receipt['state'] == 'exact-readback-accepted' and receipt['only_changed_key'] == KEY
        assert not (a.replace_owned_state / 'uncertain.json').exists()
        assert previous['metadata']['uid'] == before['metadata']['uid']
        owned_value = previous['data'][KEY]
    data = desired(before, address, owned_value)
    plan = {'configmap_uid': before['metadata']['uid'], 'resourceVersion': before['metadata']['resourceVersion'],
            'service_uid': service['metadata']['uid'], 'service_address': service['spec']['clusterIP'], 'internal_vip': address,
            'before_data': before['data'], 'after_data': data, 'key': KEY, 'host': HOST}
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    if not a.apply:
        print(json.dumps({'approval_sha256': digest, 'change_required': data != before['data'], 'service_address': service['spec']['clusterIP'], 'internal_vip': address, 'writes': False})); return
    assert a.approve_sha256 == digest, 'Fresh exact preimage approval required'
    assert a.state is not None and not a.state.exists(), 'New private state directory required; no replay'
    os.umask(0o077); a.state.mkdir(mode=0o700, parents=False)
    def save(name, obj):
        (a.state / name).write_text(json.dumps(obj, sort_keys=True))
    save('before.json', before); save('plan.json', plan); save('service-before.json', service)
    if data != before['data']:
        save('uncertain.json', {'state': 'write-about-to-start', 'approval_sha256': digest})
        result = kubectl('-n', 'kube-system', 'patch', 'configmap', 'coredns-custom', '--type=json', '-p', json.dumps(patch(before, data)), '-o', 'json')
        save('write-response.json', result)
    after = kubectl('-n', 'kube-system', 'get', 'configmap', 'coredns-custom', '-o', 'json')
    assert after['metadata']['uid'] == before['metadata']['uid'] and after['data'] == data
    current = kubectl('-n', 'kube-system', 'get', 'svc', 'traefik', '-o', 'json')
    assert current['metadata']['uid'] == service['metadata']['uid'] and current['spec']['clusterIP'] == service['spec']['clusterIP']
    save('after.json', after); save('receipt.json', {'state': 'exact-readback-accepted', 'approval_sha256': digest, 'only_changed_key': KEY, 'runtime_acceptance': 'pending', 'other_data_preserved': True})
    marker = a.state / 'uncertain.json'
    if marker.exists(): marker.unlink()
    print(json.dumps({'state': 'exact-readback-accepted', 'runtime_acceptance': 'pending', 'only_changed_key': KEY}))


if __name__ == '__main__':
    main()
