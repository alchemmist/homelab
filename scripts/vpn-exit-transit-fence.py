#!/usr/bin/env python3
"""Close direct WAN raw VPN ingress on NL, not shared HTTPS/DNS/management.

Only the new owned table is changed. An existing table must match its accepted
counter-independent projection. No client database or existing firewall mutation.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess

ROOT = Path('/var/lib/homelab-vpn-transit/exit-fence')
TABLE = 'homelab_msk_exit_fence'
RULES = '''table inet homelab_msk_exit_fence {
 chain input { type filter hook input priority -5; policy accept;
  iifname "eth0" tcp dport { 32053, 32083, 32084 } counter drop
  iifname "eth0" udp dport { 32085, 32086 } counter drop
 }
}
'''


def command(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE)


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
    assert os.geteuid() == 0 and socket.gethostname() == 'socrat-2'
    os.umask(0o077)
    route = json.loads(command(['ip', '-j', 'route', 'get', '91.189.82.238']))
    assert route[0]['dev'] == 'eth0', 'WAN interface changed; inspect rather than guess'
    if not boot:
        assert not ROOT.exists(), 'Existing apply state; inspect, never replay'
        assert subprocess.run(['nft', 'list', 'table', 'inet', TABLE], capture_output=True).returncode != 0
        ROOT.mkdir(parents=True, mode=0o700)
        (ROOT / 'before-private.json').write_text(command(['nft', '-j', 'list', 'ruleset']))
        (ROOT / 'rules.nft').write_text(RULES)
        (ROOT / 'attempt.json').write_text(json.dumps({'only_raw_wan_vpn_ports': True}))
    else:
        assert (ROOT / 'accepted.json').exists()
        assert (ROOT / 'rules.nft').read_text() == RULES
    command(['nft', '-c', '-f', str(ROOT / 'rules.nft')])
    if subprocess.run(['nft', 'list', 'table', 'inet', TABLE], capture_output=True).returncode != 0:
        command(['nft', '-f', str(ROOT / 'rules.nft')])
    observed = projection()
    if boot:
        assert observed == json.loads((ROOT / 'expected.json').read_text()), 'Unexpected table drift'
    else:
        (ROOT / 'expected.json').write_text(json.dumps(observed))
        (ROOT / 'accepted.json').write_text(json.dumps({'wan_raw_vpn_closed': True, 'shared_443_unchanged': True}))
        (ROOT / 'attempt.json').rename(ROOT / 'original-attempt.json')
    print(json.dumps({'wan_raw_vpn_closed': True, 'shared_443_dns_management_unchanged': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--apply', action='store_true')
    group.add_argument('--boot', action='store_true')
    args = parser.parse_args()
    run(boot=args.boot)
