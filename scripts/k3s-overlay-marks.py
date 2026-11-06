#!/usr/bin/env python3
"""Remove host transport skb marks at the VXLAN pod boundary, not on VPN traffic."""
import argparse
import datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess

TABLE = 'homelab_k3s_overlay_marks'
OWNER = 'homelab:k3s-overlay-marks:v1'

def run(*args, input=None, ok=(0,)):
    p = subprocess.run(args, input=input, text=True, capture_output=True, check=False)
    if p.returncode not in ok:
        raise RuntimeError(p.stderr.strip())
    return p

def rules(interface, cidr, exists):
    net = ipaddress.ip_network(cidr, strict=True)
    if net.version != 4 or not net.is_private or net.prefixlen < 16:
        raise ValueError('Require a narrow private IPv4 pod network')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', interface):
        raise ValueError('Invalid overlay interface')
    prefix = f'delete table inet {TABLE}\n' if exists else ''
    return prefix + f'''table inet {TABLE} {{
 comment "{OWNER}"
 chain pod_ingress {{
  type filter hook prerouting priority -175; policy accept;
  iifname "{interface}" ip saddr {net} ip daddr {net} meta mark != 0 counter meta mark set 0 comment "{OWNER}"
 }}
}}
'''

def desired(interface, cidr):
    net = ipaddress.ip_network(cidr)
    def match(left, right, op='=='):
        return {'match': {'op': op, 'left': left, 'right': right}}
    prefix = {'prefix': {'addr': str(net.network_address), 'len': net.prefixlen}}
    expr = [match({'meta': {'key': 'iifname'}}, interface),
            match({'payload': {'protocol': 'ip', 'field': 'saddr'}}, prefix),
            match({'payload': {'protocol': 'ip', 'field': 'daddr'}}, prefix),
            match({'meta': {'key': 'mark'}}, 0, '!='),
            {'counter': {}}, {'mangle': {'key': {'meta': {'key': 'mark'}}, 'value': 0}}]
    return [{'table': {'family': 'inet', 'name': TABLE, 'comment': OWNER}},
            {'chain': {'family': 'inet', 'table': TABLE, 'name': 'pod_ingress', 'type': 'filter',
                       'hook': 'prerouting', 'prio': -175, 'policy': 'accept'}},
            {'rule': {'family': 'inet', 'table': TABLE, 'chain': 'pod_ingress', 'expr': expr, 'comment': OWNER}}]

def owned(doc, text=''):
    table = next((x['table'] for x in doc['nftables'] if 'table' in x), {})
    if 'comment' in table:
        return table['comment'] == OWNER
    # nft 1.0.6 omits table comments from JSON, but preserves them in text.
    lines = text.splitlines()
    return len(lines) > 1 and lines[1].strip() == f'comment "{OWNER}"'

def normalize(doc):
    def clean(x):
        if isinstance(x, list):
            return [clean(v) for v in x]
        if isinstance(x, dict):
            return {k: ({} if k == 'counter' else clean(v)) for k, v in x.items() if k != 'handle'}
        return x
    result = [clean(x) for x in doc.get('nftables', []) if 'metainfo' not in x]
    for item in result:
        if 'table' in item:
            item['table'].pop('comment', None)  # ownership is verified separately
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--interface', default='flannel.1')
    p.add_argument('--pod-cidr', default='10.42.0.0/16')
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    os.umask(0o077)
    # Do not infer absence from a failed privileged read.
    tables = json.loads(run('nft', '-j', 'list', 'tables').stdout)['nftables']
    exists = any(x.get('table', {}).get('name') == TABLE and x['table'].get('family') == 'inet' for x in tables)
    before = json.loads(run('nft', '-j', 'list', 'table', 'inet', TABLE).stdout) if exists else {'nftables': []}
    before_text = run('nft', '-s', 'list', 'table', 'inet', TABLE).stdout if exists else ''
    if exists and not owned(before, before_text):
        raise RuntimeError('Refusing to replace a foreign table')
    batch = rules(args.interface, args.pod_cidr, exists)
    expected = normalize({'nftables': desired(args.interface, args.pod_cidr)})
    # Read-only kernel syntax/capability check, even when already converged.
    run('nft', '--check', '-f', '-', input=batch)
    needed = normalize(before) != expected
    if needed and args.apply:
        directory = Path('/var/lib/homelab-k3s-overlay-marks') / datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%S.%fZ')
        directory.mkdir(mode=0o700, parents=True)
        (directory / 'before.json').write_text(json.dumps(before, indent=2) + '\n')
        (directory / 'before.nft').write_text(before_text)
        # Delete/recreate only the owned table in ONE atomic netlink transaction.
        run('nft', '-f', '-', input=batch)
        after = json.loads(run('nft', '-j', 'list', 'table', 'inet', TABLE).stdout)
        (directory / 'after.json').write_text(json.dumps(after, indent=2) + '\n')
        if normalize(after) != expected:
            raise RuntimeError('Post-write verification failed: stop and inspect; do not retry blindly')
    print(json.dumps({'operations': int(needed), 'changed': bool(needed and args.apply), 'table': TABLE}))

if __name__ == '__main__':
    main()
