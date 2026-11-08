#!/usr/bin/env python3
"""Pure target-only migration plan; no panel authentication, DB writes or Xray reload.
The policy is intent, not a claim of deployed state. A native API executor and
client acceptance must be reviewed before applying this plan.
"""
from contextlib import closing
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3

spec = importlib.util.spec_from_file_location('inventory', Path(__file__).with_name('vpn-hardening-inventory.py'))
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def build(config, policy):
    if (policy.get('version') != 1 or policy.get('newVpsOrPublicIp') is not False
            or policy.get('scope') != 'existing-socrat-2-only'):
        raise ValueError('Unsupported scope')
    desired = policy['realityCorrection']
    if desired.get('apiApplyEnabled') is not False or desired.get('preserveClientMaterial') is not True:
        raise ValueError('Only preview with preserved client material is supported')
    matches = [x for x in config['inbounds'] if x['port'] == desired['port']]
    if len(matches) != 1:
        raise ValueError('Expected exactly one target inbound')
    row = matches[0]
    stream = json.loads(row['stream_settings'])
    if not row['enable'] or any((row['protocol'] != desired['protocol'],
        stream.get('network') != desired['network'], stream.get('security') != desired['security'])):
        raise ValueError('Unexpected transport or disabled inbound')
    reality = stream['realitySettings']
    if reality['serverNames'] != desired['serverNames']:
        raise ValueError('Unexpected client-visible SNI; do not migrate it implicitly')
    keys = [key for key in ('target', 'dest') if key in reality]
    if len(keys) != 1:
        raise ValueError('Ambiguous REALITY target schema')
    key = keys[0]
    current = reality[key]
    if current not in (desired['oldTarget'], desired['newTarget']):
        raise ValueError('Target drift; stop')
    after = copy.deepcopy(config)
    operations = []
    if current != desired['newTarget']:
        replacement = copy.deepcopy(stream)
        replacement['realitySettings'][key] = desired['newTarget']
        for item in after['inbounds']:
            if item['id'] == row['id']:
                item['stream_settings'] = inventory.canonical(replacement)
        operations.append({'port': row['port'], 'field': 'realitySettings.' + key,
                           'old': current, 'new': desired['newTarget']})
    result = {'before_configuration_sha256': inventory.digest(config),
              'planned_configuration_sha256': inventory.digest(after),
              'operations': operations, 'preview_only': True, 'production_writes': 0,
              'client_material_preserved': True,
              'requires_native_api_and_authenticated_client_acceptance': True}
    return {**result, 'plan_sha256': inventory.digest(result)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('/srv/x-ui-lab/db/x-ui.db'))
    parser.add_argument('--policy', type=Path, required=True)
    args = parser.parse_args()
    path = inventory.check_path(args.database)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(':memory:')) as snapshot:
            source.backup(snapshot)
            if snapshot.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('Integrity check failed')
            result = build(inventory.projection(snapshot), json.loads(args.policy.read_text()))
    print(inventory.canonical(result))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Target preview stopped on unsupported state; no writes performed') from None
