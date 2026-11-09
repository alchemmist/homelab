#!/usr/bin/env python3
"""Scoped native-API hosts.address migration. Default preview; no production SQL writes.

3x-ui v3.11.0 HostService.UpdateHostGroup reuses row IDs for same-inbound edits.
Hosts writes require admin scope (node-sync/node-admin only allow hosts/list).
Temporary admin worker expires after 20 minutes and is revoked on exit.
Never emits groups, credentials, subscription URLs, client identities or raw errors.
"""
import argparse
from contextlib import closing
import copy
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import time

_spec = importlib.util.spec_from_file_location('panel_native', Path(__file__).with_name('vpn-panel-session.py'))
native = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(native)
h = native.h
ARRAY_FIELDS = {'tags', 'snis', 'alpn', 'pinned_peer_cert_sha256', 'exclude_from_sub_types', 'node_guids'}


def configuration(database):
    with closing(sqlite3.connect(h.check_path(database).as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(':memory:')) as snapshot:
            source.backup(snapshot)
            return h.projection(snapshot)


def expected_configuration(before, old, new, group_id=None):
    expected = copy.deepcopy(before)
    for row in expected['hosts']:
        if row['address'] == old and (group_id is None or row['group_id'] == group_id):
            row['address'] = new
    return expected


def canonical_projection(config):
    config = copy.deepcopy(config)
    for row in config['hosts']:
        if 'sni_shared_random' in row:
            row['sni_shared_random'] = bool(row['sni_shared_random'])
        for key in ARRAY_FIELDS & row.keys():
            value = row[key]
            if isinstance(value, str):
                value = json.loads(value) if value else []
            row[key] = [] if value is None else value
        if not row.get('snis') and row.get('sni'):
            row['snis'] = [row['sni']]
    return {key: sorted(rows, key=h.canonical) for key, rows in config.items()}


def verify_transition(before, after, old, new, group_id=None):
    expected = expected_configuration(before, old, new, group_id)
    actual = {row['id']: row for row in after['hosts']}
    for row in expected['hosts']:
        original = next(r for r in before['hosts'] if r['id'] == row['id'])
        changed = original['address'] == old and row['address'] == new
        observed = actual.get(row['id'], {})
        if changed and 'updated_at' in row and observed.get('updated_at') != row['updated_at']:
            stamp = observed.get('updated_at')
            if not isinstance(stamp, (int, float)):
                return False
            seconds = stamp / (1000 if stamp > 100000000000 else 1)
            if not time.time() - 600 <= seconds <= time.time() + 10:
                return False
            row['updated_at'] = stamp
    return canonical_projection(after) == canonical_projection(expected)


def payload(group, old, new):
    result = copy.deepcopy(group)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', result.get('groupId', '')):
        raise ValueError('Invalid host group identity')
    if not isinstance(result.get('hosts'), list) or not result.get('inboundIds'):
        raise ValueError('Unexpected native host DTO')
    for index, value in enumerate(result['hosts']):
        if value == old:
            result['hosts'][index] = new
        elif value.startswith(old + ':'):
            port = value[len(old)+1:]
            if not port.isdigit() or not 0 < int(port) < 65536:
                raise ValueError('Unexpected host port')
            result['hosts'][index] = new + ':' + port
    if result['hosts'] == group['hosts']:
        raise ValueError('Native group does not contain the approved old address')
    return result


def preview(state, old, new):
    import ipaddress
    if old == new or not all(ipaddress.ip_address(v).is_global for v in (old, new)):
        raise ValueError('Require distinct public literal addresses')
    session = native.NativeSession(state, worker_scope='admin')
    before = configuration(session.database)
    rows = [r for r in before['hosts'] if r['address'] == old]
    if not rows:
        raise ValueError('No old-address rows; read acceptance instead of replaying')
    return session, before, {'session': session.preview(), 'old': old, 'new': new,
        'configuration_sha256': h.digest(before), 'rows': len(rows),
        'groups': len({r['group_id'] for r in rows})}


def apply(state, old, new, approval):
    session, before, plan = preview(state, old, new)
    if approval != h.digest(plan):
        raise ValueError('Fresh approved migration hash required')
    session.open(h.digest(plan['session']))
    try:
        if configuration(session.database) != before:
            raise ValueError('Configuration drift after credential creation')
        groups = session.call('GET', '/hosts/list')
        targets = {r['group_id'] for r in before['hosts'] if r['address'] == old}
        chosen = [g for g in groups if g['groupId'] in targets]
        if len(chosen) != len(targets) or {g['groupId'] for g in chosen} != targets:
            raise ValueError('Native group ownership mismatch')
        candidates = [(g, payload(g, old, new)) for g in chosen]
        h.save(session.state / 'host-migration-plan-private.json', {'plan': plan, 'groups': chosen})
        current = before
        for index, (group, candidate) in enumerate(candidates):
            if canonical_projection(configuration(session.database)) != canonical_projection(current):
                raise ValueError('Configuration drift before native host update')
            fresh = session.call('GET', '/hosts/get/' + group['groupId'])
            if fresh != group:
                raise ValueError('Native host DTO drift before update')
            marker = session.state / ('host-uncertain-' + str(index) + '.json')
            h.save(marker, {'group': group['groupId'], 'before_sha256': h.digest(current), 'state': 'attempting'})
            session.call('POST', '/hosts/update/' + group['groupId'], candidate)
            after = configuration(session.database)
            expected = expected_configuration(current, old, new, group['groupId'])
            h.save(session.state / ('host-after-private-' + str(index) + '.json'), after)
            if not verify_transition(current, after, old, new, group['groupId']):
                raise RuntimeError('Native host invariant mismatch; stop, do not replay')
            h.save(session.state / ('host-verified-' + str(index) + '.json'), {'group': group['groupId'], 'invariants': True})
            marker.unlink()
            current = after
        if not verify_transition(before, current, old, new):
            raise RuntimeError('Final host invariants failed')
        proof = {'host_rows_updated': plan['rows'], 'groups_updated': plan['groups'],
                 'identities_preserved': len(current['clients']), 'bindings_preserved': len(current['client_inbounds']),
                 'only_address_changed_semantically': True, 'native_updated_at_and_null_false_normalization': True, 'reload_performed': False,
                 'subscription_delivery_unproven': True}
        h.save(session.state / 'host-migration-acceptance.json', proof)
    finally:
        session.cleanup()
    return dict(proof, temporary_tokens_removed=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--old-ip', required=True)
    p.add_argument('--new-ip', required=True)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--approve-sha256')
    a = p.parse_args()
    try:
        if a.apply:
            print(h.canonical(apply(a.state, a.old_ip, a.new_ip, a.approve_sha256)))
        else:
            _, _, plan = preview(a.state, a.old_ip, a.new_ip)
            print(h.canonical({'approval_sha256': h.digest(plan), 'rows': plan['rows'], 'groups': plan['groups'], 'writes': 0}))
    except Exception:
        raise SystemExit('Host migration stopped; inspect private receipts and readback, never replay writes blindly.') from None
