#!/usr/bin/env python3
"""One-time legacy chat-admission split, preserving reviewed native chat users.

This is NOT future-user provisioning. New infrastructure observers never receive
chat-use grants. Existing chats, OIDC subjects, passwords and MFA are untouched.
Default audits only; use the native bootstrap's private credential file on socrat-0.
"""
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import urllib.parse

SPEC = importlib.util.spec_from_file_location('observer_bootstrap', Path(__file__).with_name('observer-access-bootstrap.py'))
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)
require = bootstrap.planner.require
CHAT = 'homelab-chat-user'


def snapshot(client, policy):
    users = []
    for identity in policy['legacyChatPreservation']:
        found = client.rows('core/users/?' + urllib.parse.urlencode({'username': identity['username']}))
        user = bootstrap.planner.exact(found, 'username', identity['username'])
        require(user.get('uuid') == identity['uuid'], 'Legacy chat subject mismatch')
        users.append({k: user[k] for k in ['pk', 'uuid', 'username', 'groups']})
    app = bootstrap.planner.exact(client.rows('core/applications/?superuser_full_list=true'), 'slug', 'open-webui')
    return {'users': users, 'groups': client.rows('core/groups/'),
            'app': {k: app[k] for k in ['pk', 'slug', 'provider', 'policy_engine_mode']},
            'bindings': client.rows('policies/bindings/?target=' + str(app['pk']))}


def build(state, policy):
    require(policy['legacyChatPreservation'] == [
        {'username': 'antropophag', 'uuid': '6015c85b-82e9-49ce-a4e3-0270c676e26d'}], 'Unreviewed legacy preservation scope')
    require(state['app']['slug'] == 'open-webui' and state['app']['policy_engine_mode'] == 'any'
            and state['app']['provider'] is not None, 'Unexpected native chat application')
    observer = bootstrap.planner.exact(state['groups'], 'name', 'homelab-observer')
    owner = bootstrap.planner.exact(state['groups'], 'name', 'homelab-owner')
    require(len(state['users']) == len(policy['legacyChatPreservation'])
            and {(u['username'], u['uuid']) for u in state['users']} ==
                {(u['username'], u['uuid']) for u in policy['legacyChatPreservation']}, 'Unreviewed user snapshot')
    expected = {u['pk'] for u in state['users']}
    require(set(observer['users']) <= expected | set(owner['users']), 'Unreviewed existing observer: audit native chat preservation first')
    for identity in policy['legacyChatPreservation']:
        user = bootstrap.planner.exact(state['users'], 'username', identity['username'])
        require(user['uuid'] == identity['uuid'], 'Immutable legacy subject mismatch')
    matches = [g for g in state['groups'] if g['name'] == CHAT]
    require(len(matches) <= 1, 'Ambiguous chat-use group')
    group = matches[0] if matches else None
    if group:
        require(group.get('is_superuser') is False and group.get('roles') == [] and group.get('parents') == [],
                'Chat group carries inherited/IdP administration privileges')
    operations = []
    if not group:
        operations.append({'action': 'create-chat-group'})
    for user in state['users']:
        if not group or group['pk'] not in user['groups']:
            operations.append({'action': 'preserve-chat-user', 'username': user['username'], 'uuid': user['uuid'], 'pk': user['pk']})
    bindings = state['bindings']
    require(all(b['target'] == state['app']['pk'] and b.get('enabled') is True and b.get('negate') is False
                and b.get('policy') is None and b.get('user') is None and b.get('failure_result') is False
                and b.get('group') for b in bindings), 'Complex/unsafe legacy chat policy')
    chat_bindings = [b for b in bindings if group and b.get('group') == group['pk']]
    require(len(chat_bindings) <= 1, 'Duplicate chat admission')
    require(any(b.get('group') == owner['pk'] for b in bindings), 'Owner chat recovery admission missing')
    if not chat_bindings:
        operations.append({'action': 'admit-chat-group', 'app': state['app']['pk']})
    old = [b for b in bindings if b.get('group') == observer['pk']]
    require(len(old) <= 1, 'Duplicate observer chat binding')
    if old:
        operations.append({'action': 'remove-observer-chat-admission', 'binding': old[0]['pk'],
                           'app': state['app']['pk'], 'group': observer['pk']})
    return operations


def apply(client, operation, state):
    action = operation['action']
    if action == 'create-chat-group':
        client.call('authentik', 'POST', 'core/groups/',
                    {'name': CHAT, 'is_superuser': False, 'roles': [], 'parents': [], 'attributes': {}})
        return
    # Generated group UUIDs are resolved from the native API, never guessed or
    # substituted from an arbitrary operation path supplied by a user.
    group = bootstrap.planner.exact(client.rows('core/groups/'), 'name', CHAT)
    require(group.get('is_superuser') is False and group.get('roles') == [] and group.get('parents') == [], 'Unsafe chat group')
    if action == 'preserve-chat-user':
        user = client.call('authentik', 'GET', 'core/users/' + str(operation['pk']) + '/')
        require(user['uuid'] == operation['uuid'] and user['username'] == operation['username'], 'Subject changed before grant')
        client.call('authentik', 'POST', 'core/groups/' + group['pk'] + '/add_user/', {'pk': user['pk']})
    elif action == 'admit-chat-group':
        client.call('authentik', 'POST', 'policies/bindings/',
                    {'target': operation['app'], 'group': group['pk'], 'enabled': True,
                     'negate': False, 'failure_result': False, 'order': 100, 'policy': None, 'user': None})
    elif action == 'remove-observer-chat-admission':
        current = client.call('authentik', 'GET', 'policies/bindings/' + operation['binding'] + '/')
        require(current['target'] == operation['app'] and current['group'] == operation['group']
                and current.get('policy') is None and current.get('user') is None, 'Binding changed; stop')
        # Read back the preservation state BEFORE removing legacy admission.
        ready = snapshot(client, {'legacyChatPreservation': [{'username': u['username'], 'uuid': u['uuid']} for u in state['users']]})
        pending = build(ready, {'legacyChatPreservation': [{'username': u['username'], 'uuid': u['uuid']} for u in state['users']]})
        require(pending == [operation], 'Legacy users not safely admitted or policy drifted before removal')
        client.call('authentik', 'DELETE', 'policies/bindings/' + operation['binding'] + '/')
    else:
        raise ValueError('Unreviewed migration operation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', required=True, type=Path)
    parser.add_argument('--state', type=Path, default=Path('/var/lib/homelab-observer-chat-migration'))
    parser.add_argument('--policy', type=Path, default=bootstrap.planner.ROOT / 'deploy/identity/observer/profile.json')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--approve-plan-hash')
    args = parser.parse_args()
    os.umask(0o077)
    bootstrap.private(args.credentials.parent, directory=True)
    bootstrap.private(args.credentials)
    require(args.state.is_absolute() and not args.state.is_symlink(), 'Private absolute state required')
    args.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    bootstrap.private(args.state, directory=True)
    with (args.state / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not (args.state / 'uncertain.json').exists(), 'Uncertain migration; inspect before retry')
        client = bootstrap.Client(json.loads(args.credentials.read_text()))
        policy = json.loads(args.policy.read_text())
        before = snapshot(client, policy)
        operations = build(before, policy)
        approved = bootstrap.digest(before, policy, operations)
        if not args.apply:
            print(json.dumps({'applied': False, 'plan_hash': approved, 'operations': operations}))
            return
        require(args.approve_plan_hash == approved, 'Fresh approved migration hash required')
        fresh = snapshot(client, policy)
        require(bootstrap.digest(fresh, policy, build(fresh, policy)) == approved, 'Concurrent migration change')
        run = args.state / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        run.mkdir(mode=0o700)
        bootstrap.save(run / 'before.json', before)
        bootstrap.save(run / 'operations.json', operations)
        bootstrap.save(args.state / 'uncertain.json', {'plan_hash': approved, 'run': str(run)})
        for i, operation in enumerate(operations):
            apply(client, operation, before)
            bootstrap.save(run / ('progress-' + str(i) + '.json'), operation)
        after = snapshot(client, policy)
        require(not build(after, policy), 'Migration readback not converged')
        bootstrap.save(run / 'after.json', after)
        bootstrap.save(run / 'receipt.json', {'state': 'configured', 'future_per_user_sync': False,
                                             'passwords_mfa_native_subjects_and_chat_data_untouched': True})
        (args.state / 'uncertain.json').unlink()
        print(json.dumps({'applied': True, 'operations': len(operations), 'future_per_user_sync': False}))


if __name__ == '__main__':
    main()
