#!/usr/bin/env python3
"""One-time correction of the reviewed initial observer's IdP membership.

NOT future user provisioning. Ordinary onboarding is a group add + native SSO.
No passwords/MFA, native app users, roles, NetBird settings or other groups change.
Default is GET/plan only. Apply requires a fresh hash, private acceptance evidence,
a second snapshot and private receipts. Uncertain writes stop, never blind retry.
"""
import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path

UUID = '9547c492-d757-43f0-8476-98a9c33c4155'
READONLY = 'acc10f26-5658-4ea1-9704-92bfebccaec2'
NETBIRD = 'a033c844-3d5b-41db-a7cc-697c1a7c0f4f'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def plan(user, observer):
    require(user['pk'] == 94 and user['uuid'] == UUID, 'Initial subject identity mismatch')
    require(user['is_active'] is True and user['is_superuser'] is False, 'Initial human status drift')
    require(observer['name'] == 'homelab-observer' and observer['is_superuser'] is False
            and observer['roles'] == [] and observer['parents'] == [], 'Observer carries unrelated IdP authority')
    groups = user['groups']
    require(isinstance(groups, list) and len(groups) == len(set(groups)) and NETBIRD in groups,
            'Approved NetBird membership missing or ambiguous')
    ops = []
    if observer['pk'] not in groups:
        ops.append({'path': 'core/groups/' + observer['pk'] + '/add_user/', 'body': {'pk': 94}})
    if READONLY in groups:
        ops.append({'path': 'core/groups/' + READONLY + '/remove_user/', 'body': {'pk': 94}})
    return ops


def fingerprint(user, observer):
    stable = {k: user[k] for k in ['pk', 'uuid', 'is_active', 'is_superuser', 'groups', 'password_change_date']}
    return hashlib.sha256(json.dumps({'subject': stable, 'observer': observer, 'operations': plan(user, observer)},
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--acceptance', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--approve-plan-hash')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('observer_bootstrap', Path(__file__).with_name('observer-access-bootstrap.py'))
    boot = importlib.util.module_from_spec(spec); spec.loader.exec_module(boot)
    os.umask(0o077)
    boot.private(args.credentials.parent, directory=True); boot.private(args.credentials)
    require(args.state.is_absolute() and not args.state.is_symlink(), 'Private absolute state required')
    args.state.mkdir(mode=0o700, parents=True, exist_ok=True); boot.private(args.state, directory=True)
    def save(name, value):
        boot.save(args.state/name, value)
    with (args.state/'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not (args.state/'uncertain.json').exists(), 'Inspect uncertain receipt before any retry')
        client = boot.Client(json.loads(args.credentials.read_text()))
        def snapshot():
            user = client.call('authentik', 'GET', 'core/users/94/')
            observer = boot.planner.exact(client.rows('core/groups/'), 'name', 'homelab-observer')
            return user, observer
        before, group = snapshot(); ops = plan(before, group); digest = fingerprint(before, group)
        if not args.apply:
            print(json.dumps({'writes': False, 'plan_hash': digest, 'operations': ops,
                              'netbird_preserved': True, 'password_mfa_changes': False, 'native_user_provisioning': False}))
            return
        require(args.approve_plan_hash == digest, 'Exact fresh approval required')
        require(args.acceptance is not None, 'Private live acceptance receipt required')
        boot.private(args.acceptance)
        accepted = json.loads(args.acceptance.read_text())
        require(accepted.get('nativeObserverAcceptanceReady') is True
                and set(accepted.get('services', [])) == {'rancher', 'wiki', 'argocd', 'grafana'}
                and accepted.get('harborGated') is True, 'Native acceptance incomplete')
        fresh, fresh_group = snapshot()
        require(fingerprint(fresh, fresh_group) == digest, 'Concurrent identity change; stop')
        save('before.json', before); save('operations.json', ops)
        save('uncertain.json', {'plan_hash': digest, 'started': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        for index, op in enumerate(ops):
            client.call('authentik', 'POST', op['path'], op['body'])
            save('progress.json', {'completed': index + 1})
        after, after_group = snapshot()
        require(not plan(after, after_group), 'Membership readback not converged')
        expected = set(before['groups']) - {READONLY} | {group['pk']}
        require(set(after['groups']) == expected and after['password_change_date'] == before['password_change_date'],
                'Unexpected unrelated group/password metadata change; inspect receipts')
        save('after.json', after)
        save('receipt.json', {'subject_uuid': UUID, 'operations': len(ops), 'observer_member': True,
                             'idp_readonly_removed': True, 'netbird_preserved': True,
                             'password_mfa_writes': False, 'native_user_provisioning': False})
        (args.state/'uncertain.json').unlink()
        print(json.dumps({'applied': True, 'operations': len(ops), 'observer_member': True,
                          'idp_readonly_removed': True, 'netbird_preserved': True,
                          'password_mfa_writes': False, 'native_user_provisioning': False}))


if __name__ == '__main__':
    main()
