#!/usr/bin/env python3
"""Preview/install an ACCEPT-only nft counter table for two raw VPN backends.
No reject/drop/NAT, no packet logging, no panel/SSH/WG/443 changes. Not a firewall
hardening completion receipt: client inventory is required before enforcing anything.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess

spec = importlib.util.spec_from_file_location('vpn_inventory', Path(__file__).with_name('vpn-hardening-inventory.py'))
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
TABLE = 'homelab_xui_backend_audit'
OWNER = 'homelab issue83 counter-only v1'
INTERFACES = ('lo', 'wg-socrat', 'cni0', 'flannel.1', 'nb-host')
PORTS = (12096, 32087)


def rules():
    lines = ['table inet ' + TABLE + ' {', ' comment "' + OWNER + '"',
             ' chain input {', '  type filter hook input priority -5; policy accept;']
    for port in PORTS:
        for interface in INTERFACES:
            lines.append('  iifname "' + interface + '" tcp dport ' + str(port) + ' counter comment "' + str(port) + ':' + interface + '"')
        lines.append('  iifname != { ' + ', '.join('"' + x + '"' for x in INTERFACES) + ' } tcp dport ' + str(port) + ' counter comment "' + str(port) + ':other"')
    return '\n'.join(lines + [' }', '}']) + '\n'


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in ('packets', 'bytes', 'handle', 'metainfo')}
    if isinstance(value, list):
        return [stable(x) for x in value if not (isinstance(x, dict) and 'metainfo' in x)]
    return value


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20, **kwargs)
    if result.returncode:
        raise RuntimeError('nft operation failed; inspect private state')
    return result.stdout


def read_table():
    # Read the ruleset so permission errors cannot masquerade as an absent table.
    data = json.loads(run(['nft', '-j', 'list', 'ruleset']))['nftables']
    selected = [item for item in data if any(isinstance(obj, dict) and obj.get('family') == 'inet' and
                (obj.get('table') == TABLE or (kind == 'table' and obj.get('name') == TABLE))
                for kind, obj in item.items())]
    if not selected:
        return None
    tables = [x['table'] for x in selected if 'table' in x]
    if len(tables) != 1 or tables[0].get('comment') != OWNER:
        raise ValueError('Unowned existing table; refusing modification')
    return selected


def plan(current):
    return {'table': TABLE, 'policy': 'accept', 'ports': list(PORTS),
            'rules_sha256': hashlib.sha256(rules().encode()).hexdigest(),
            'before_sha256': helpers.digest(stable(current)),
            'packet_logging': False, 'enforcement': False}


def apply(approval, state):
    if socket.gethostname() != 'socrat-2' or os.geteuid() != 0:
        raise ValueError('Apply requires root on socrat-2')
    directory = helpers.private_directory(state)
    fd = os.open(directory/'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if any(p.name != 'lock' for p in directory.iterdir()):
            raise ValueError('State exists; inspect receipts instead of replaying')
        before = read_table()
        if before is not None:
            raise ValueError('Counter table already exists; do not reset observations')
        desired = plan(before)
        if approval != helpers.digest(desired):
            raise ValueError('Fresh exact plan hash required')
        batch = rules()
        run(['nft', '--check', '-f', '-'], input=batch)
        if stable(read_table()) != stable(before):
            raise ValueError('Table changed before apply')
        helpers.save(directory/'before.json', before)
        helpers.save(directory/'uncertain.json', {'plan_sha256': approval})
        run(['nft', '-f', '-'], input=batch)
        after = read_table()
        if after is None or len([x for x in after if 'rule' in x]) != len(PORTS) * (len(INTERFACES) + 1):
            raise RuntimeError('Unexpected readback; inspect uncertain state')
        helpers.save(directory/'after.json', after)
        helpers.save(directory/'receipt.json', {**desired, 'installed': True})
        (directory/'uncertain.json').unlink()
        return {**desired, 'installed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--approve-plan-hash')
    parser.add_argument('--state', type=Path)
    parser.add_argument('--observe', action='store_true', help='Read existing counters, no writes')
    parser.add_argument('--render', action='store_true', help='Offline rules only; no nft call')
    args = parser.parse_args()
    if args.render:
        if args.apply or args.observe:
            parser.error('Render cannot be combined with apply/observe')
        print(rules(), end='')
    elif args.apply:
        if not args.state or not args.approve_plan_hash or args.observe:
            parser.error('Apply requires private state and exact approval, without observe')
        print(helpers.canonical(apply(args.approve_plan_hash, args.state)))
    else:
        current = read_table()
        if args.observe:
            print(helpers.canonical(current))
        else:
            desired = plan(current)
            print(helpers.canonical({**desired, 'plan_sha256': helpers.digest(desired)}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Counter audit stopped; no automatic retry/rollback. Inspect private receipts.') from None
