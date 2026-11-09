#!/usr/bin/env python3
"""Owned HOME→NL fixed-service DNAT via Moscow; never alters default routes.

Initial --apply requires fresh state. --boot validates the persisted exact rule
projection. A service-start failure retains a destination-specific prohibit route.
Unknown ports are intentionally NOT claimed as migrated by this tool.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess

ROOT = Path('/var/lib/homelab-vpn-transit/home-egress')
TABLE = 'homelab_msk_home_egress'
EXIT = '109.120.141.60'


def command(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE)


def rules():
    body = '''
 ip daddr 109.120.141.60 tcp dport 53 counter dnat ip to 10.250.0.40:53
 ip daddr 109.120.141.60 udp dport 53 counter dnat ip to 10.250.0.40:53
 ip daddr 109.120.141.60 tcp dport { 80, 443, 32053, 32083, 32084, 51840 } counter dnat ip to 91.189.82.238
 ip daddr 109.120.141.60 udp dport { 443, 32085, 32086 } counter dnat ip to 91.189.82.238
 ip daddr 109.120.141.60 udp dport 51830 counter dnat ip to 91.189.82.238:51832
'''
    return ('table inet ' + TABLE + ' {\n'
            ' chain prerouting { type nat hook prerouting priority dstnat; policy accept;\n' + body + ' }\n'
            ' chain output { type nat hook output priority dstnat; policy accept;\n' + body + ' }\n'
            ' chain postrouting { type nat hook postrouting priority srcnat; policy accept;\n'
            ' ip daddr 10.250.0.40 tcp dport 53 counter masquerade\n'
            ' ip daddr 10.250.0.40 udp dport 53 counter masquerade\n }\n}\n')


def projection():
    value = json.loads(command(['nft', '-j', 'list', 'table', 'inet', TABLE]))
    def clean(v):
        if isinstance(v, list):
            return [clean(x) for x in v if not isinstance(x, dict) or 'metainfo' not in x]
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if k not in ('handle', 'packets', 'bytes')}
        return v
    return clean(value)


def run(boot=False):
    assert os.geteuid() == 0 and socket.gethostname() in ('socrat-0', 'socrat-1', 'socrat-3')
    os.umask(0o077)
    source = rules()
    digest = hashlib.sha256(source.encode()).hexdigest()
    if not boot:
        assert not json.loads(command(['ip', '-4', '-j', 'route', 'show', 'exact', EXIT + '/32'])), 'Unowned destination route: stop'
        assert not ROOT.exists(), 'Existing state; inspect instead of replaying'
        assert subprocess.run(['nft', 'list', 'table', 'inet', TABLE], capture_output=True).returncode != 0
        ROOT.mkdir(parents=True, mode=0o700)
        (ROOT / 'rules.nft').write_text(source)
        (ROOT / 'before-private.json').write_text(command(['nft', '-j', 'list', 'ruleset']))
        (ROOT / 'attempt.json').write_text(json.dumps({'rules_sha256': digest}))
    else:
        assert (ROOT / 'accepted.json').exists(), 'Unaccepted state: retain fence, inspect'
        assert (ROOT / 'rules.nft').read_text() == source
    command(['nft', '-c', '-f', str(ROOT / 'rules.nft')])
    present = subprocess.run(['nft', 'list', 'table', 'inet', TABLE], capture_output=True).returncode == 0
    if not present:
        command(['nft', '-f', str(ROOT / 'rules.nft')])
    observed = projection()
    if boot:
        assert observed == json.loads((ROOT / 'expected.json').read_text()), 'Unexpected live table drift'
    else:
        (ROOT / 'expected.json').write_text(json.dumps(observed, sort_keys=True))
        (ROOT / 'accepted.json').write_text(json.dumps({'rules_sha256': digest, 'only_owned_table_added': True}))
        (ROOT / 'attempt.json').rename(ROOT / 'original-attempt.json')
    # Only the startup safety fence belonging to this service may be removed.
    fence = ['ip', '-4', 'route', 'del', 'prohibit', EXIT + '/32', 'metric', '32760']
    removed = subprocess.run(fence, capture_output=True, check=False)
    if boot:
        assert removed.returncode == 0, "Startup safety fence could not be removed: inspect"
    print(json.dumps({'node': socket.gethostname(), 'known_nl_services_via_moscow': True,
                      'default_routes_unchanged': True, 'unknown_ports_not_claimed': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--apply', action='store_true')
    group.add_argument('--boot', action='store_true')
    args = parser.parse_args()
    run(boot=args.boot)
