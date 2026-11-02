"""Explicit owner-admin API migration. Never run as part of normal reconciliation.
The legacy credential key remains an alias for existing consumers, not a bootstrap token.
apply/check never delete humans; retire-akadmin is a separate explicit guarded action. Never prints credentials.
"""
import argparse
import fcntl
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.request
from urllib.parse import quote

NAME = 'homelab-identity-automation'
GROUP = 'homelab-identity-automation-admin'
OWNER_UUID = '9e33877a-3eaa-4541-98eb-8cdc10088ef6'
BASE = 'https://auth.socrat.alchemmist.xyz/api/v3/'

def save(path, data):
    tmp = path.with_name(path.name + '.tmp-' + secrets.token_hex(8))
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def api(token, method, path, data=None):
    req = urllib.request.Request(BASE + path, method=method,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read(); return json.loads(raw) if raw else None

def exact(token, endpoint, field, value):
    rows = api(token, 'GET', endpoint + '?' + field + '=' + quote(value, safe='') + '&page_size=1000')['results']
    rows = [r for r in rows if r[field] == value]
    if len(rows) > 1: raise RuntimeError('Ambiguous managed identity')
    return rows[0] if rows else None

def verify(token, journal):
    user = api(token, 'GET', 'core/users/' + str(journal['user_pk']) + '/')
    group = api(token, 'GET', 'core/groups/' + journal['group_pk'] + '/')
    marker = {'homelab_automation_journal': journal['nonce']}
    if not (user['uuid'] == journal['user_uuid'] and user['username'] == NAME
            and user['type'] == 'service_account' and user['is_active']
            and user['is_superuser'] and user['attributes'] == marker
            and user['groups'] == [journal['group_pk']]
            and group['name'] == GROUP and group['is_superuser']
            and group['attributes'] == marker and set(group['users']) == {user['pk']}):
        raise RuntimeError('Managed account/group drift')
    t = api(token, 'GET', 'core/tokens/' + quote(NAME, safe='') + '/')
    if t['user'] != user['pk'] or t['intent'] != 'api' or t['expiring']:
        raise RuntimeError('Managed token drift')
    owner = exact(token, 'core/users/', 'username', 'alchemmist')
    if not owner or owner['uuid'] != OWNER_UUID or not owner['is_active'] or not owner['is_superuser']:
        raise RuntimeError('Owner admin prerequisite failed')
    for endpoint in ['providers/all/', 'core/applications/', 'flows/instances/', 'outposts/instances/']:
        api(token, 'GET', endpoint + '?page_size=1')
    return user

def migrate(root, action):
    if root.stat().st_mode & 0o077: raise RuntimeError('Deployment directory is not private')
    path = root / 'automation-api.json'; credentials = root / 'credentials.json'
    if credentials.stat().st_mode & 0o077: raise RuntimeError('Credential file is not private')
    values = json.loads(credentials.read_text()); old = values['AUTHENTIK_BOOTSTRAP_TOKEN']
    journal = json.loads(path.read_text()) if path.exists() else None
    if journal and journal.get('status') == 'active':
        if path.stat().st_mode & 0o077: raise RuntimeError('Journal is not private')
        verify(journal['token'], journal)
        if old != journal['token']: raise RuntimeError('Consumer credential alias drift')
        print('PASS: dedicated machine API identity and consumer alias verified; akadmin untouched')
        return
    if action == 'check':
        print('NOT MIGRATED: no active machine API journal'); return
    owner = exact(old, 'core/users/', 'username', 'alchemmist')
    if not owner or owner['uuid'] != OWNER_UUID or not owner['is_superuser'] or not owner['is_active']:
        raise RuntimeError('Owner admin prerequisite failed')
    if journal is None:
        if exact(old, 'core/users/', 'username', NAME) or exact(old, 'core/groups/', 'name', GROUP):
            raise RuntimeError('Refusing adoption of existing identity')
        # List metadata only; never overwrite an existing token identifier.
        tokens = api(old, 'GET', 'core/tokens/?page_size=1000')['results']
        if any(t['identifier'] == NAME for t in tokens): raise RuntimeError('Foreign token identifier')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = root / ('credentials-before-automation-' + stamp + '.json')
        if backup.exists(): raise RuntimeError('Backup already exists')
        save(backup, values)
        journal = {'version': 1, 'nonce': secrets.token_hex(24), 'status': 'preparing',
                   'previous_credentials': backup.name, 'token_identifier': NAME}
        save(path, journal)
    marker = {'homelab_automation_journal': journal['nonce']}
    group = exact(old, 'core/groups/', 'name', GROUP)
    if group and group['attributes'] != marker: raise RuntimeError('Foreign group')
    if group is None:
        group = api(old, 'POST', 'core/groups/', {'name': GROUP, 'is_superuser': True, 'attributes': marker})
    if not group['is_superuser']: raise RuntimeError('Group permission drift')
    journal['group_pk'] = group['pk']; save(path, journal)
    user = exact(old, 'core/users/', 'username', NAME)
    if user and user['attributes'] != marker: raise RuntimeError('Foreign user')
    if user is None:
        if group['users']: raise RuntimeError('Foreign group member')
        user = api(old, 'POST', 'core/users/', {'username': NAME, 'name': 'Homelab identity automation',
            'type': 'service_account', 'path': 'service-accounts/homelab',
            'is_active': True, 'groups': [group['pk']], 'attributes': marker})
    journal.update(user_pk=user['pk'], user_uuid=user['uuid']); save(path, journal)
    tokens = api(old, 'GET', 'core/tokens/?page_size=1000')['results']
    matches = [t for t in tokens if t['identifier'] == NAME]
    if matches:
        if len(matches) != 1 or matches[0]['user'] != user['pk'] or matches[0].get('description') != journal['nonce']:
            raise RuntimeError('Foreign token')
    else:
        api(old, 'POST', 'core/tokens/', {'identifier': NAME, 'user': user['pk'],
            'intent': 'api', 'expiring': False, 'description': journal['nonce']})
    journal['token'] = api(old, 'GET', 'core/tokens/' + NAME + '/view_key/')['key']
    verify(journal['token'], journal)
    # Validate new access before atomically switching any existing consumer.
    values['AUTHENTIK_BOOTSTRAP_TOKEN'] = journal['token']
    save(credentials, values)
    journal['status'] = 'active'; save(path, journal)
    print('PASS: dedicated machine API access activated; old akadmin/token retained for guarded rollback')


def retire_default_admin(root):
    """Only after an independent node-admin recovery drill and encrypted backup."""
    import subprocess
    migrate(root, 'check')
    path = root/'automation-api.json'; journal = json.loads(path.read_text())
    evidence = journal.get('recovery_evidence', {})
    if not (evidence.get('fixture_admin_session_verified') is True
            and evidence.get('fixture_cleanup_verified') is True
            and evidence.get('owner_uuid') == OWNER_UUID
            and journal.get('encrypted_backup_sha256')):
        raise RuntimeError('Recovery and off-node backup prerequisites not recorded')
    env = dict(os.environ, K3S_CONFIG_FILE='/dev/null')
    k = ['kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml', '-n', 'identity']
    secret = json.loads(subprocess.check_output(k+['get','secret','authentik-runtime','-o','json'], env=env))
    keys = {'AUTHENTIK_BOOTSTRAP_TOKEN','AUTHENTIK_BOOTSTRAP_PASSWORD'}
    if keys.intersection(secret.get('data', {})):
        raise RuntimeError('Runtime Secret still contains bootstrap credentials')
    annotation = secret['metadata'].get('annotations', {}).get('kubectl.kubernetes.io/last-applied-configuration', '{}')
    applied = json.loads(annotation)
    if keys.intersection(applied.get('data', {})) or keys.intersection(applied.get('stringData', {})):
        raise RuntimeError('Runtime Secret annotation still contains bootstrap credentials')
    for name in ['authentik-server','authentik-worker']:
        deploy=json.loads(subprocess.check_output(k+['get','deploy',name,'-o','json'],env=env))
        for c in deploy['spec']['template']['spec']['containers']:
            if keys.intersection(e['name'] for e in c.get('env', [])):
                raise RuntimeError('Explicit pod bootstrap environment remains')
    bootstrap=(root/'bootstrap.py').read_text()
    if 'runtime_values.pop(key,None)' not in bootstrap or 'automation-api.json' not in bootstrap:
        raise RuntimeError('Future bootstrap reconciliation is not migration-aware')
    token=journal['token'];target=exact(token,'core/users/','username','akadmin')
    if target is None:
        if journal.get('akadmin_retired_at'):
            print('PASS: akadmin already retired');return
        raise RuntimeError('Default admin missing without retirement journal')
    if target['uuid'] != 'fc86d87d-3a72-4cfb-8ba1-aa6bf6b017e7' or target['pk'] != 4:
        raise RuntimeError('Refusing deletion of an unreviewed identity')
    tokens=api(token,'GET','core/tokens/?page_size=1000')['results']
    owned=[t for t in tokens if t['user']==target['pk']]
    if any(t['identifier']!='authentik-bootstrap-token' for t in owned):
        raise RuntimeError('Unexpected default-admin token dependency')
    journal['retired_user_before']=target;save(path,journal)
    api(token,'DELETE','core/users/'+str(target['pk'])+'/')
    if exact(token,'core/users/','username','akadmin') is not None:
        raise RuntimeError('Default admin removal not confirmed')
    if any(t['user']==target['pk'] for t in api(token,'GET','core/tokens/?page_size=1000')['results']):
        raise RuntimeError('Default-admin token survived deletion')
    verify(token,journal)
    values=json.loads((root/'credentials.json').read_text())
    if values['AUTHENTIK_BOOTSTRAP_TOKEN'] != token: raise RuntimeError('Consumer alias changed during retirement')
    values.pop('AUTHENTIK_BOOTSTRAP_PASSWORD',None);save(root/'credentials.json',values)
    journal['akadmin_retired_at']=datetime.now(timezone.utc).isoformat();save(path,journal)
    print('PASS: exact reviewed akadmin and its bootstrap token retired; machine access and personal owner verified')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('--action', choices=['check', 'apply', 'retire-akadmin'], default='check')
    p.add_argument('--confirm-delete-akadmin', action='store_true')
    a = p.parse_args()
    if a.action == 'retire-akadmin' and not a.confirm_delete_akadmin:
        p.error('retire-akadmin requires --confirm-delete-akadmin')
    try:
        # Serialize migration and retries; consumers only read atomically replaced files.
        with (a.root / 'automation-migration.lock').open('a') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if a.action == 'retire-akadmin': retire_default_admin(a.root)
            else: migrate(a.root, a.action)
    except Exception as e:
        print('Migration stopped safely (' + type(e).__name__ + '); inspect protected journal, never print keys', file=sys.stderr)
        sys.exit(1)
