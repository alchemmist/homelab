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


DIRECT_PROBE_UID = 19091
DIRECT_PROBE_COMMENT = "homelab-direct-ip-probe"


def rules(direct_probe=None):
    body = '''
 ip daddr 109.120.141.60 tcp dport 53 counter dnat ip to 10.250.0.40:53
 ip daddr 109.120.141.60 udp dport 53 counter dnat ip to 10.250.0.40:53
 ip daddr 109.120.141.60 tcp dport { 80, 443, 32053, 32083, 32084, 51840 } counter dnat ip to 91.189.82.238
 ip daddr 109.120.141.60 udp dport { 443, 32085, 32086 } counter dnat ip to 91.189.82.238
 ip daddr 109.120.141.60 udp dport 51830 counter dnat ip to 91.189.82.238:51832
'''
    if direct_probe is None:
        direct_probe = socket.gethostname() == 'socrat-0'
    bypass = (' ip daddr 109.120.141.60 tcp dport 443 meta skuid '
              + str(DIRECT_PROBE_UID) + ' counter return comment "'
              + DIRECT_PROBE_COMMENT + '"\n') if direct_probe else ''
    return ('table inet ' + TABLE + ' {\n'
            ' chain prerouting { type nat hook prerouting priority dstnat; policy accept;\n' + body + ' }\n'
            ' chain output { type nat hook output priority dstnat; policy accept;\n' + bypass + body + ' }\n'
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


def upgrade_direct_probe():
    """One-shot CAS migration of HOME0's owned table; no flush/delete/reload."""
    assert os.geteuid() == 0 and socket.gethostname() == 'socrat-0'
    os.umask(0o077)
    old = rules(direct_probe=False)
    assert (ROOT / 'rules.nft').read_text() == old, 'Not the reviewed legacy source'
    before = projection()
    assert before == json.loads((ROOT / 'expected.json').read_text()), 'Live drift: stop'
    assert json.loads((ROOT / 'accepted.json').read_text())['rules_sha256'] == hashlib.sha256(old.encode()).hexdigest()
    receipt = ROOT / 'direct-probe-upgrade'
    assert not receipt.exists(), 'Existing attempt: inspect receipts, never replay'
    receipt.mkdir(mode=0o700)
    for name in ('rules.nft', 'expected.json', 'accepted.json'):
        (receipt / (name + '.before')).write_bytes((ROOT / name).read_bytes())
    batch = ('insert rule inet ' + TABLE + ' output ip daddr ' + EXIT
             + ' tcp dport 443 meta skuid ' + str(DIRECT_PROBE_UID)
             + ' counter return comment "' + DIRECT_PROBE_COMMENT + '"\n')
    (receipt / 'insert.nft').write_text(batch)
    command(['nft', '-c', '-f', str(receipt / 'insert.nft')])
    command(['nft', '-f', str(receipt / 'insert.nft')])
    after = projection()
    added = [v for v in after['nftables'] if v.get('rule', {}).get('comment') == DIRECT_PROBE_COMMENT]
    expected_expr = [
        {'match': {'op': '==', 'left': {'payload': {'protocol': 'ip', 'field': 'daddr'}}, 'right': EXIT}},
        {'match': {'op': '==', 'left': {'payload': {'protocol': 'tcp', 'field': 'dport'}}, 'right': 443}},
        {'match': {'op': '==', 'left': {'meta': {'key': 'skuid'}}, 'right': DIRECT_PROBE_UID}},
        {'counter': {}}, {'return': None}]
    assert len(added) == 1 and added[0]['rule']['chain'] == 'output'
    assert added[0]['rule']['expr'] == expected_expr, 'Unexpected inserted rule: inspect'
    without = dict(after, nftables=[v for v in after['nftables'] if v not in added])
    assert without == before, 'Unrelated change: inspect'
    output_rules = [v['rule'] for v in after['nftables'] if v.get('rule', {}).get('chain') == 'output']
    assert output_rules[0]['comment'] == DIRECT_PROBE_COMMENT
    new = rules(direct_probe=True)
    (ROOT / 'rules.nft').write_text(new)
    (ROOT / 'expected.json').write_text(json.dumps(after, sort_keys=True))
    accepted = {'rules_sha256': hashlib.sha256(new.encode()).hexdigest(),
                'only_owned_table_added': True, 'direct_probe_uid': DIRECT_PROBE_UID,
                'only_home0_local_tcp443_probe_bypasses_moscow': True}
    (ROOT / 'accepted.json').write_text(json.dumps(accepted, sort_keys=True))
    (receipt / 'accepted.json').write_text(json.dumps(accepted, sort_keys=True))
    assert projection() == after
    print(json.dumps({'direct_probe_upgrade': True, 'uid': DIRECT_PROBE_UID,
                      'ordinary_traffic_unchanged': True}))


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
    group.add_argument('--upgrade-direct-probe', action='store_true')
    args = parser.parse_args()
    if args.upgrade_direct_probe:
        upgrade_direct_probe()
    else:
        run(boot=args.boot)
