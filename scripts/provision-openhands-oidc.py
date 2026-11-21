#!/usr/bin/env python3
"""Register only OpenHands' native Authentik OIDC client for official oauth2-proxy.

Default GET-only plan. No users, memberships, flows, outposts or other apps change.
Apply requires the exact plan hash and a fresh encrypted identity backup receipt.
Credentials stay in private operator files and the identity-namespace proxy Secret.
"""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('iam', ROOT / 'scripts/spi-queue-oidc.py')
iam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iam)
HOST = 'openhands.socrat.alchemmist.xyz'
CLIENT = 'socrat-openhands'
APP = {'name':'OpenHands', 'slug':'openhands', 'group':'Socrat',
       'meta_launch_url':'https://' + HOST + '/canvas/', 'policy_engine_mode':'any',
       'meta_description':'Owner-only single-tenant Agent Canvas. Grants shell and shared workspace access.'}
PROVIDER = {'name':'homelab-openhands', 'client_id':CLIENT, 'client_type':'confidential',
            'sub_mode':'user_uuid', 'grant_types':['authorization_code','refresh_token'],
            'include_claims_in_id_token':True, 'access_token_validity':'minutes=5',
            'refresh_token_validity':'hours=8', 'issuer_mode':'per_provider',
            'redirect_uris':[{'matching_mode':'strict','url':'https://' + HOST + '/oauth2/callback'}]}


def encode_cookie_secret(raw):
    iam.require(len(raw) == 32, 'Cookie key must contain exactly32 bytes')
    # oauth2-proxy SecretBytes uses Go RawURLEncoding, not standard base64.
    return base64.urlsafe_b64encode(raw).decode()


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())


def inspect(api):
    owner = iam.one(api, 'core/groups/', 'name', 'homelab-owner')
    iam.require(owner is not None, 'Existing owner group missing')
    flows = {key:iam.one(api,'flows/instances/','slug',value) for key,value in iam.FLOWS.items()}
    iam.require(all(flows.values()), 'Existing authentication/consent/invalidation flow missing')
    signing = iam.one(api,'crypto/certificatekeypairs/','name','authentik Self-signed Certificate')
    iam.require(signing is not None, 'Existing signing key missing')
    mappings = api.rows('propertymappings/provider/scope/')
    selected = []
    for scope in ['openid','profile','email','offline_access']:
        found = [v for v in mappings if v.get('managed') == 'goauthentik.io/providers/oauth2/scope-' + scope]
        iam.require(len(found) == 1, 'Missing/ambiguous standard scope: ' + scope)
        selected.append(found[0]['pk'])
    groups = [v for v in mappings if v.get('name') == 'homelab-groups' and v.get('scope_name') == 'groups']
    iam.require(len(groups) == 1 and groups[0].get('expression') == 'return {"groups": [group.name for group in request.user.ak_groups.all()]}', 'Groups mapping drift')
    settings = {**PROVIDER,'signing_key':signing['pk'],'property_mappings':selected + [groups[0]['pk']],
                **{key:value['pk'] for key,value in flows.items()}}
    provider = iam.one(api,'providers/oauth2/','name',PROVIDER['name'])
    by_client = iam.one(api,'providers/oauth2/','client_id',CLIENT)
    iam.require((provider or {}).get('pk') == (by_client or {}).get('pk'), 'Client-id collision')
    app = iam.one(api,'core/applications/','slug',APP['slug'])
    return owner, settings, provider, app


def validate(api, owner, settings, provider, app, journal):
    iam.require(provider and app and journal and journal.get('status') == 'active', 'Partial identity or missing private journal; no adoption/reset')
    for key,value in settings.items():
        actual = provider.get(key)
        if key in ['property_mappings','grant_types']: actual,value = sorted(actual or []),sorted(value)
        if key == 'redirect_uris': actual,value = iam.canonical_redirects(actual),iam.canonical_redirects(value)
        iam.require(actual == value, 'OIDC provider drift: ' + key)
    iam.require(provider['pk'] == journal['provider_pk'] and str(app['pk']) == str(journal['app_pk']), 'Identity ownership drift')
    iam.require(secrets.compare_digest(provider.get('client_secret',''),journal['client_secret']), 'Client-secret drift; no rotation')
    iam.require(app.get('provider') == provider['pk'] and all(app.get(k) == v for k,v in APP.items()), 'Application drift')
    bindings = api.rows('policies/bindings/?target=' + str(app['pk']))
    iam.require(len(bindings) == 1, 'Unexpected application bindings')
    b = bindings[0]
    iam.require(b.get('group') == owner['pk'] and not b.get('user') and not b.get('policy') and b.get('enabled') is True and not b.get('negate') and not b.get('failure_result'), 'Owner-only admission binding drift')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    private = Path.home()/'.config/homelab/openhands'
    p.add_argument('--credentials',type=Path,default=private/'authentik-api-token.json')
    p.add_argument('--state-dir',type=Path,default=private/'oidc')
    p.add_argument('--backup-receipt',type=Path,default=private/'oidc-backup-receipt.json')
    p.add_argument('--apply',action='store_true')
    p.add_argument('--approve-plan-hash')
    a = p.parse_args()
    os.umask(0o077)
    a.state_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    iam.require(not a.state_dir.is_symlink() and not a.state_dir.stat().st_mode & 0o077, 'Unsafe state directory')
    lock = os.open(a.state_dir/'lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    marker = a.state_dir/'uncertain.json'
    file = a.state_dir/'client.json'
    iam.require(not marker.exists(), 'Uncertain prior write; inspect manually, do not retry')
    journal = None
    if file.exists():
        iam.private(file)
        journal = json.loads(file.read_text())
    api = iam.API(a.credentials)
    owner, settings, provider, app = inspect(api)
    if provider or app: validate(api,owner,settings,provider,app,journal)
    else: iam.require(journal is None, 'Private journal without live identity; stop')
    context = {'application':APP,'provider':settings,'owner_group':owner['pk'],'existing':bool(provider),
               'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    digest = hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
    if not a.apply:
        print(json.dumps({'plan_hash':digest,'creates':0 if provider else 3,'allowed_group':'homelab-owner','existing_identities_modified':False}))
        return
    iam.require(a.approve_plan_hash == digest, 'Exact fresh plan approval required')
    if not provider:
        iam.private(a.backup_receipt)
        receipt = json.loads(a.backup_receipt.read_text())
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(receipt['observedAt'])).total_seconds()
        backup = Path(receipt['encryptedBackup'])
        iam.private(backup)
        iam.require(0 <= age <= 3600 and hashlib.sha256(backup.read_bytes()).hexdigest() == receipt['sha256'], 'Fresh valid encrypted backup required')
        write_private(marker,{'plan_hash':digest})
        journal = {'status':'pending','client_secret':secrets.token_urlsafe(48),'cookie_secret':encode_cookie_secret(secrets.token_bytes(32))}
        write_private(file,journal)
        api = iam.API(a.credentials,write=True)
        provider = api.call('POST','providers/oauth2/',{**settings,'client_secret':journal['client_secret']})
        app = api.call('POST','core/applications/',{**APP,'provider':provider['pk']})
        api.call('POST','policies/bindings/',{'target':app['pk'],'group':owner['pk'],'order':0,'enabled':True,'negate':False,'failure_result':False})
        journal.update(status='active',provider_pk=provider['pk'],app_pk=app['pk'])
        # Private journal already exists with mode0600; do not follow symlinks.
        fd = os.open(file,os.O_WRONLY|os.O_TRUNC|os.O_NOFOLLOW)
        with os.fdopen(fd,'w') as f:
            json.dump(journal,f)
            f.flush()
            os.fsync(f.fileno())
        owner,settings,provider,app = inspect(api)
        validate(api,owner,settings,provider,app,journal)
        marker.unlink()
    # Credential delivery is operator-only; never mount this Secret in Canvas.
    old = subprocess.check_output(['kubectl','-n','identity','get','secret','openhands-oidc','--ignore-not-found','-o','json'])
    if old.strip():
        old = json.loads(old)
        iam.require(old['metadata'].get('labels',{}).get('homelab-app') == 'openhands', 'Unexpected existing Secret owner')
    payload = {'apiVersion':'v1','kind':'Secret','metadata':{'name':'openhands-oidc','namespace':'identity','labels':{'homelab-app':'openhands'}},
               'type':'Opaque','stringData':{'client-id':CLIENT,'client-secret':journal['client_secret'],'cookie-secret':journal['cookie_secret']}}
    if old:
        for name,value in payload['stringData'].items():
            iam.require(secrets.compare_digest(base64.b64decode(old.get('data',{}).get(name,'')),value.encode()), 'Runtime Secret drift; no silent rotation')
    else:
        subprocess.run(['kubectl','create','-f','-'],input=json.dumps(payload).encode(),stdout=subprocess.DEVNULL,check=True)
    print('OpenHands OIDC ready: existing owner group only; proxy Secret delivered; values withheld')


if __name__ == '__main__':
    try:main()
    except Exception as exc:
        raise SystemExit('STOP: '+(str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)+'; inspect private state/uncertain marker; values withheld') from None
