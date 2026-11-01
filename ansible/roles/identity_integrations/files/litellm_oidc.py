#!/usr/bin/env python3
"""Explicit LiteLLM native OIDC rollout. No real password resets or key rotation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import urllib.request

HOST = 'auth.socrat.alchemmist.xyz'
BASE = 'https://' + HOST
OWNER_ID = 'socrat-admin'
MAPPING = 'homelab-litellm-reviewed-identity'


def identity_expression(owner_uid, owner_email):
    # Identities/roles are selected by reviewed immutable subject, never email.
    return ('uid = str(request.user.uuid)\n'
            'owner = uid.replace("-", "") == ' + repr(owner_uid.replace('-', '')) + '\n'
            'return {"litellm_user_id": ' + repr(OWNER_ID) + ' if owner else "authentik:" + uid,\n'
            ' "litellm_user_email": ' + repr(owner_email) + ' if owner else uid + "@sso.socrat.alchemmist.xyz",\n'
            ' "litellm_user_role": "proxy_admin" if owner else "internal_user_viewer"}\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('--public-edge', default='109.173.40.247')
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **kw: original(args.public_edge if host == HOST else host, *a, **kw)
    os.environ.setdefault('K3S_CONFIG_FILE', '/dev/null')
    kube = ['kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml', '-n', 'llm']
    credentials = json.loads((args.root / 'credentials.json').read_text())
    def api(method, path, payload=None):
        req = urllib.request.Request(BASE + '/api/v3/' + path, method=method,
            headers={'Authorization': 'Bearer ' + credentials['AUTHENTIK_BOOTSTRAP_TOKEN'], 'Content-Type': 'application/json'},
            data=json.dumps(payload).encode() if payload is not None else None)
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read(); return json.loads(body) if body else None
    def kubectl(arguments, data=None):
        r = subprocess.run(kube + arguments, input=data, capture_output=True, timeout=90)
        if r.returncode:
            raise RuntimeError('Kubernetes operation failed; output suppressed to protect credentials')
        return r.stdout
    def private(path, data, overwrite=False):
        if path.exists() and not overwrite:
            return
        with open(path, 'w', opener=lambda p, f: os.open(p, f, 0o600)) as out:
            json.dump(data, out, indent=2)
        path.chmod(0o600)
    def one(path, field, value):
        rows = api('GET', path + '?page_size=100' + ('&superuser_full_list=true' if path == 'core/applications/' else ''))['results']
        found = [r for r in rows if r[field] == value]
        if len(found) > 1: raise RuntimeError('Ambiguous configuration')
        return found[0] if found else None

    if api('GET', 'admin/version/')['version_current'] != '2026.8.5':
        raise RuntimeError('Unreviewed Authentik version')
    deployment = json.loads(kubectl(['get', 'deployment', 'litellm', '-o', 'json']))
    container = deployment['spec']['template']['spec']['containers'][0]
    if container['image'] != 'ghcr.io/berriai/litellm:1.105.1':
        raise RuntimeError('Unreviewed LiteLLM version')
    query = '''import asyncio,json
from prisma import Prisma
async def main():
 db=Prisma();await db.connect()
 try:
  rows=await db.query_raw('SELECT user_id,user_role,user_email,password,sso_user_id FROM "LiteLLM_UserTable"')
  print(json.dumps(rows,default=str))
 finally:await db.disconnect()
asyncio.run(main())
'''
    raw = kubectl(['exec', '-i', 'deployment/litellm', '--', 'python', '-'], query.encode())
    users = json.loads(raw.decode().splitlines()[-1])
    owner_rows = [r for r in users if r['user_id'] == OWNER_ID and r['user_role'] == 'proxy_admin']
    if len(owner_rows) != 1 or len(users) > 5:
        raise RuntimeError('Reviewed owner identity / free-tier capacity gate failed')
    if any(r.get('password') for r in users if r['user_id'] != OWNER_ID):
        raise RuntimeError('Non-owner password identity requires explicit review')
    owner = one('core/users/', 'username', 'alchemmist')
    group = one('core/groups/', 'name', 'homelab-owner')
    reviewed = json.loads((args.root / 'account-mappings.json').read_text())['alchemmist']
    if not owner or owner['uuid'] != reviewed.get('idpUserUuid') or reviewed.get('litellmUserId') != OWNER_ID:
        raise RuntimeError('Owner UUID differs from explicit reviewed account mapping')
    if not group or owner['pk'] not in group.get('users', []):
        raise RuntimeError('Reviewed owner group boundary missing')
    if not args.apply:
        print('Preflight passed: native OIDC available, reviewed owner and owner-only local password boundary; no changes')
        return
    private(args.root / 'litellm-users-before-oidc.json', users)
    private(args.root / 'litellm-deployment-before-oidc.json', deployment)
    binding_path = args.root / 'litellm-owner-binding.json'
    expected_binding = {'authentik_uuid': owner['uuid'], 'litellm_user_id': OWNER_ID}
    if binding_path.exists():
        binding = json.loads(binding_path.read_text())
        # One-time upgrade from the initial same-owner hashed UID journal.
        if binding == {'authentik_uid': owner['uid'], 'litellm_user_id': OWNER_ID}:
            private(args.root / 'litellm-owner-hashed-uid-original.json', binding)
            private(binding_path, expected_binding, overwrite=True)
        elif binding != expected_binding:
            raise RuntimeError('Owner subject drift; refusing automatic rebind')
    else:
        private(binding_path, expected_binding)
    client_path = args.root / 'oidc-clients.json'
    clients = json.loads(client_path.read_text())
    if 'litellm' not in clients:
        if one('providers/oauth2/', 'name', 'homelab-litellm'):
            raise RuntimeError('Existing provider without retained client secret')
        clients['litellm'] = {'client_id': 'socrat-litellm', 'client_secret': secrets.token_urlsafe(48)}
        private(client_path, clients, overwrite=True)
    mapping = one('propertymappings/provider/scope/', 'name', MAPPING)
    settings = {'name': MAPPING, 'scope_name': 'litellm_identity',
                'expression': identity_expression(owner['uuid'], owner_rows[0]['user_email'])}
    if not mapping or any(mapping.get(k) != v for k, v in settings.items()):
        mapping = api('PATCH' if mapping else 'POST', 'propertymappings/provider/scope/' + (mapping['pk'] + '/' if mapping else ''), settings)
    scopes = api('GET', 'propertymappings/provider/scope/?page_size=100')['results']
    mappings = [r['pk'] for r in scopes if r['scope_name'] in ['openid', 'profile', 'email']] + [mapping['pk']]
    flows = {r['slug']: r['pk'] for r in api('GET', 'flows/instances/?page_size=100')['results']}
    cert = one('crypto/certificatekeypairs/', 'name', 'authentik Self-signed Certificate')
    provider = one('providers/oauth2/', 'name', 'homelab-litellm')
    settings = {'name': 'homelab-litellm', 'client_type': 'confidential', **clients['litellm'],
        'grant_types': ['authorization_code', 'refresh_token'], 'sub_mode': 'user_uuid',
        'authentication_flow': flows['default-authentication-flow'],
        'authorization_flow': flows['default-provider-authorization-explicit-consent'],
        'invalidation_flow': flows['default-provider-invalidation-flow'],
        'property_mappings': mappings, 'signing_key': cert['pk'],
        'redirect_uris': [{'matching_mode': 'strict', 'url': 'https://llm.alchemmist.xyz/sso/callback'}],
        'include_claims_in_id_token': True, 'access_token_validity': 'minutes=5', 'refresh_token_validity': 'hours=8'}
    provider = api('PATCH' if provider else 'POST', 'providers/oauth2/' + (str(provider['pk']) + '/' if provider else ''), settings)
    manifest = json.loads((args.root / 'service-icons/sources.json').read_text())
    icon = 'service-icons/litellm-' + manifest['files']['litellm.svg']['sha256'][:12] + '.svg'
    app = one('core/applications/', 'slug', 'litellm')
    settings = {'name': 'LiteLLM', 'slug': 'litellm', 'provider': provider['pk'],
        'meta_launch_url': 'https://llm.alchemmist.xyz/sso/key/generate', 'meta_icon': icon,
        'meta_description': 'LLM gateway administration. Machine API keys remain separate.',
        'group': 'Socrat', 'policy_engine_mode': 'any'}
    app = api('PATCH' if app else 'POST', 'core/applications/' + ('litellm/' if app else ''), settings)
    bindings = api('GET', 'policies/bindings/?target=' + app['pk'] + '&page_size=100')['results']
    if any(b.get('group') != group['pk'] for b in bindings):
        raise RuntimeError('Unexpected application admission binding; review before rollout')
    if not bindings:
        api('POST', 'policies/bindings/', {'target': app['pk'], 'group': group['pk'], 'order': 0, 'enabled': True, 'failure_result': False})
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'socrat-authentik-litellm', 'namespace': 'llm'}, 'type': 'Opaque', 'stringData': {
        'GENERIC_CLIENT_ID': clients['litellm']['client_id'], 'GENERIC_CLIENT_SECRET': clients['litellm']['client_secret'],
        'GENERIC_AUTHORIZATION_ENDPOINT': BASE + '/application/o/authorize/',
        'GENERIC_TOKEN_ENDPOINT': BASE + '/application/o/token/',
        'GENERIC_USERINFO_ENDPOINT': BASE + '/application/o/userinfo/',
        'GENERIC_SCOPE': 'openid profile email litellm_identity', 'GENERIC_CLIENT_USE_PKCE': 'true',
        'GENERIC_USER_ID_ATTRIBUTE': 'litellm_user_id', 'GENERIC_USER_EMAIL_ATTRIBUTE': 'litellm_user_email',
        'GENERIC_USER_ROLE_ATTRIBUTE': 'litellm_user_role', 'PROXY_BASE_URL': 'https://llm.alchemmist.xyz'}}
    import base64
    old = kubectl(['get', 'secret', 'socrat-authentik-litellm', '--ignore-not-found', '-o', 'json'])
    old_data = json.loads(old).get('data', {}) if old else {}
    changed_secret = any(old_data.get(k) != base64.b64encode(v.encode()).decode() for k, v in secret['stringData'].items())
    kubectl(['apply', '-f', '-'], json.dumps(secret).encode())
    env_from = container.get('envFrom', [])
    has_mount = any(e.get('secretRef', {}).get('name') == 'socrat-authentik-litellm' for e in env_from)
    if not has_mount or changed_secret:
        if not has_mount: env_from = env_from + [{'secretRef': {'name': 'socrat-authentik-litellm'}}]
        patch = {'spec': {'template': {'spec': {'containers': [{'name': container['name'], 'envFrom': env_from}]}}}}
        patch['spec']['template']['metadata'] = {'annotations': {'socrat.alchemmist.xyz/oidc-env-sha256': hashlib.sha256(json.dumps(secret['stringData'], sort_keys=True).encode()).hexdigest()}}
        kubectl(['patch', 'deployment', 'litellm', '--type=strategic', '-p', json.dumps(patch)])
        print('Native OIDC configured; graceful rolling update started. Do not force-delete draining pods.')
    else:
        print('Native OIDC configuration reconciled; no deployment restart requested')


if __name__ == '__main__':
    main()
