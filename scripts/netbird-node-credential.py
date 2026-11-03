#!/usr/bin/env python3
"""Explicit one-time service-user bootstrap or daily bounded PAT renewal.

Admin API capability is broad in this NetBird edition, not least privilege.
Never create/modify a human, emit a token, or keep the bootstrap credential.
"""
import argparse
import datetime as dt
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('reconcile', Path(__file__).with_name('netbird-node-reconcile.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def credential(result, user_id):
    metadata = result['personal_access_token']
    return {'user_id': user_id, 'token_id': metadata['id'], 'token': result['plain_token'],
            'expiration_date': metadata['expiration_date']}


def renew(folder, config, bootstrap=None):
    path = folder/'credential.json'
    intent = folder/'credential-intent.json'
    mod.require(not intent.exists(), 'uncertain prior credential operation; inspect locally')
    if not path.exists():
        mod.require(bootstrap is not None, 'initial credential needs explicit trusted bootstrap-token-file')
        # The temporary runtime object never persists the bootstrap token.
        runtime = object.__new__(mod.Runtime)
        runtime.auth = {'token': json.loads(bootstrap.read_text())['personal_access_token']}
        users = runtime.api('GET', 'users')
        mod.require(not any(u.get('name') == mod.SERVICE for u in users),
                    'same-name service user already exists; no name adoption')
        mod.atomic(intent, {'phase': 'creating-service-user'})
        user = runtime.api('POST', 'users', {'name': mod.SERVICE, 'is_service_user': True,
                                            'role': 'admin', 'auto_groups': []})
        mod.require(user['is_service_user'] and user['role'] == 'admin', 'service-user type mismatch')
        mod.atomic(intent, {'phase': 'issuing-token', 'user_id': user['id']})
        issued = runtime.api('POST', 'users/'+user['id']+'/tokens', {'name': 'inventory-onboarding', 'expires_in': 365})
        new = credential(issued, user['id'])
    else:
        runtime = mod.Runtime(folder, config)
        user = mod.unique(runtime.api('GET', 'users'), 'id', runtime.auth['user_id'])
        mod.require(user['is_service_user'] and user['role'] == 'admin' and not user['is_blocked'],
                    'bound service account changed; no automatic role repair')
        deadline = dt.datetime.fromisoformat(runtime.auth['expiration_date'].replace('Z', '+00:00'))
        if deadline - dt.datetime.now(dt.timezone.utc) > dt.timedelta(days=30):
            return False
        mod.atomic(intent, {'phase': 'renewing-token', 'user_id': user['id'], 'old_token_id': runtime.auth['token_id']})
        issued = runtime.api('POST', 'users/'+user['id']+'/tokens', {'name': 'inventory-onboarding', 'expires_in': 365})
        new = credential(issued, user['id'])
    previous = runtime.auth
    runtime.auth = new
    mod.unique(runtime.api('GET', 'users'), 'id', new['user_id'])
    # Persist the new valid token before revoking the old one. Intent remains on
    # any ambiguous failure, including failure after the atomic switch.
    mod.atomic(path, new)
    if previous.get('token_id'):
        runtime.api('DELETE', 'users/'+new['user_id']+'/tokens/'+previous['token_id'])
    intent.unlink()
    return True


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--bootstrap-token-file', type=Path)
    args = parser.parse_args()
    mod.require(args.state_dir.is_dir() and not args.state_dir.is_symlink()
                and not args.state_dir.stat().st_mode & 0o077, 'private state directory required')
    config = mod.validate_config(json.loads(args.config.read_text()))
    with (args.state_dir/'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        changed = renew(args.state_dir, config, args.bootstrap_token_file)
    print(json.dumps({'changed': changed, 'status': 'service-credential-valid'}))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'status': 'blocked', 'error_type': type(e).__name__,
                          'reason': str(e) if isinstance(e, ValueError) else 'credential error; details redacted'}))
        sys.exit(1)
