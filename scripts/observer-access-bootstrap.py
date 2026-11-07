#!/usr/bin/env python3
"""One-time bounded native configuration bootstrap; NOT a user sync daemon.

Run on socrat-0 after reviewed Argo RBAC activation. Default audits only.
Private credential JSON: authentikToken and either harborJobserviceSecret or
harborUsername + harborPassword (explicit native machine vs admin mode).
Kubernetes uses the existing local k3s admin certificate, never a copied token.
"""
import argparse
import base64
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import pwd
from pathlib import Path
import ssl
import urllib.error
import urllib.parse
import urllib.request

SPEC = importlib.util.spec_from_file_location('observer_plan', Path(__file__).with_name('observer-access-plan.py'))
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def private(path, directory=False, owner_uid=None):
    expected_uid = os.geteuid() if owner_uid is None else owner_uid
    planner.require(not path.is_symlink() and path.exists() and path.stat().st_uid == expected_uid
                    and not path.stat().st_mode & 0o077
                    and (path.is_dir() if directory else path.is_file()), 'Unsafe private path')


def readiness_directory(path):
    # Foundation is deployed into the existing alchemmist-owned 0700 cache.
    # Keep strict caller ownership everywhere else; do not chown that directory.
    owner_uid = None
    if os.geteuid() == 0 and path == Path('/home/alchemmist/.cache/homelab-authentik'):
        owner_uid = pwd.getpwnam('alchemmist').pw_uid
    private(path, directory=True, owner_uid=owner_uid)


def validate_path(system, path):
    planner.require(isinstance(path, str) and path and not any(c.isspace() for c in path)
                    and not any(c in path for c in ['\\', '#']) and '://' not in path
                    and not path.startswith('//'), 'Unsafe API path')
    parsed = urllib.parse.urlsplit(path)
    decoded = parsed.path
    for _ in range(3):
        decoded = urllib.parse.unquote(decoded)
    planner.require('%' not in decoded and not any(p in {'.', '..'} for p in decoded.split('/'))
                    and not any(c in decoded for c in ['\\', '?', '#']), 'Unsafe API path traversal')
    prefixes = {'kubernetes': ('/apis/management.cattle.io/v3/',),
                'harbor': ('/api/v2.0/',),
                'authentik': ('core/groups/', 'core/users/', 'core/applications/', 'policies/bindings/')}
    planner.require(system in prefixes and parsed.path.startswith(prefixes[system]), 'API path outside reviewed namespace')


def harbor_authorization(credentials):
    if 'harborJobserviceSecret' in credentials:
        secret = credentials['harborJobserviceSecret']
        planner.require(isinstance(secret, str) and secret and not any(c.isspace() for c in secret), 'Invalid native Harbor machine credential')
        return 'Harbor-Secret ' + secret, '/api/v2.0/internalconfig'
    username, password = credentials['harborUsername'], credentials['harborPassword']
    planner.require(isinstance(username, str) and username and ':' not in username
                    and isinstance(password, str) and password, 'Invalid Harbor admin credential')
    return 'Basic ' + base64.b64encode((username + ':' + password).encode()).decode(), '/api/v2.0/configurations'


class Client:
    def __init__(self, credentials):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        context = ssl.create_default_context(cafile='/var/lib/rancher/k3s/server/tls/server-ca.crt')
        context.load_cert_chain('/var/lib/rancher/k3s/server/tls/client-admin.crt',
                                '/var/lib/rancher/k3s/server/tls/client-admin.key')
        self.origins = {'kubernetes': 'https://127.0.0.1:6443',
                        'authentik': 'https://auth.socrat.alchemmist.xyz/api/v3/',
                        'harbor': 'https://harbor.socrat.alchemmist.xyz'}
        self.openers = {name: urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=context if name == 'kubernetes' else ssl.create_default_context()))
            for name in self.origins}
        harbor_header, self.harbor_config_path = harbor_authorization(credentials)
        self.auth = {'authentik': 'Bearer ' + credentials['authentikToken'], 'harbor': harbor_header}

    def call(self, system, method, path, body=None):
        validate_path(system, path)
        headers = {'Content-Type': 'application/json-patch+json' if system == 'kubernetes' and method == 'PATCH' else 'application/json'}
        if system in self.auth:
            headers['Authorization'] = self.auth[system]
        request = urllib.request.Request(self.origins[system] + path, method=method, headers=headers,
                                         data=None if body is None else json.dumps(body).encode())
        try:
            with self.openers[system].open(request, timeout=30) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                planner.require(len(data) <= 8 * 1024 * 1024, 'API response bound exceeded')
                return json.loads(data) if data else None
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise RuntimeError('Native API request failed or write uncertain: ' + system + ' HTTP ' + str(status)) from None

    def rows(self, path):
        result = []
        for page in range(1, 101):
            data = self.call('authentik', 'GET', path + ('&' if '?' in path else '?') + 'page_size=100&page=' + str(page))
            result.extend(data['results'])
            if not data['pagination'].get('next'):
                return result
        raise RuntimeError('Incomplete IdP pagination')

    def harbor_members(self, project):
        result = []
        for page in range(1, 101):
            data = self.call('harbor', 'GET', '/api/v2.0/projects/' + project + '/members?page_size=100&page=' + str(page))
            result.extend(data)
            if len(data) < 100:
                return result
        raise RuntimeError('Incomplete Harbor pagination')


    def harbor_groups(self):
        result = []
        for page in range(1, 101):
            data = self.call('harbor', 'GET', '/api/v2.0/usergroups?group_name=homelab-observer&page_size=100&page=' + str(page))
            result.extend(g for g in data if g.get('group_name') == 'homelab-observer')
            if len(data) < 100:
                return result
        raise RuntimeError('Incomplete Harbor group pagination')


def snapshot(client, policy):
    kbase = '/apis/management.cattle.io/v3/'
    get = lambda path: client.call('kubernetes', 'GET', kbase + path)
    globals_ = get('globalroles')['items']
    cluster = policy['rancher']['cluster']
    config = client.call('harbor', 'GET', client.harbor_config_path)
    value = lambda key: config[key]['value']
    apps = client.rows('core/applications/?superuser_full_list=true')
    apps = [{k: app[k] for k in ['slug', 'pk', 'provider', 'policy_engine_mode']}
            for app in apps]
    return {'groups': client.rows('core/groups/'), 'apps': apps,
            'bindings': client.rows('policies/bindings/'), 'globalRoles': globals_,
            'rancherLoginRole': next(r for r in globals_ if r['metadata']['name'] == policy['rancher']['globalRole']),
            'rancherClusterRole': get('roletemplates/' + policy['rancher']['clusterRole']),
            'rancherGroupBinding': get('namespaces/' + cluster + '/clusterroletemplatebindings/homelab-observer-group'),
            'rancherSessionSetting': get('settings/auth-user-session-ttl-minutes'),
            'rancherAuth': get('authconfigs/genericoidc'),
            'harbor': {'groups': client.harbor_groups(), 'oidcGroupsClaim': value('oidc_groups_claim'), 'oidcAdminGroup': value('oidc_admin_group'),
                       'projectCreationRestriction': value('project_creation_restriction'),
                       'projects': {name: client.harbor_members(name) for name in policy['harbor']['projects']}}}


def normalized(value):
    if isinstance(value, dict):
        # Computed signed media URLs do not define group membership or access.
        return {k: normalized(v) for k, v in value.items() if k != 'meta_icon_url'}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def digest(state, policy, operations):
    return hashlib.sha256(json.dumps({'snapshot': normalized(state), 'policy': policy, 'operations': operations},
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', required=True, type=Path)
    parser.add_argument('--state', type=Path, default=Path('/var/lib/homelab-observer-bootstrap'))
    parser.add_argument('--policy', type=Path, default=planner.ROOT / 'deploy/identity/observer/profile.json')
    parser.add_argument('--authentik-directory', type=Path, help='Existing protected foundation directory for readiness receipt')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--approve-plan-hash')
    args = parser.parse_args()
    os.umask(0o077)
    private(args.credentials.parent, directory=True)
    private(args.credentials)
    if args.authentik_directory:
        readiness_directory(args.authentik_directory)
        planner.require(not (args.authentik_directory / 'observer-ready.json').exists(), 'Readiness receipt already exists; inspect before replacing')
    planner.require(args.state.is_absolute() and not args.state.is_symlink(), 'Private absolute state path required')
    args.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    private(args.state, directory=True)
    with (args.state / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        planner.require(not (args.state / 'uncertain.json').exists(), 'Uncertain run: inspect receipts, never blindly retry')
        client = Client(json.loads(args.credentials.read_text()))
        policy = json.loads(args.policy.read_text())
        before = snapshot(client, policy)
        operations = planner.build(before, policy)
        approved = digest(before, policy, operations)
        if not args.apply:
            print(json.dumps({'applied': False, 'operations': len(operations), 'plan_hash': approved,
                              'targets': [{'system': op['system'], 'method': op['method'], 'path': op['path']} for op in operations]}, indent=2))
            return
        planner.require(args.approve_plan_hash == approved, 'Fresh reviewed plan hash required')
        # Full fresh read before the first mutation protects the approval scope.
        fresh = snapshot(client, policy)
        planner.require(digest(fresh, policy, planner.build(fresh, policy)) == approved, 'Concurrent configuration change')
        run = args.state / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        run.mkdir(mode=0o700)
        save(run / 'before.json', before)
        save(run / 'operations.json', operations)
        save(args.state / 'uncertain.json', {'plan_hash': approved, 'run': str(run)})
        completed = []
        for op in operations:
            client.call(op['system'], op['method'], op['path'], op['body'])
            completed.append({'system': op['system'], 'path': op['path']})
            save(run / ('progress-' + str(len(completed)) + '.json'), completed)
        after = snapshot(client, policy)
        planner.require(not planner.build(after, policy), 'Native readback not converged; inspect private receipts')
        save(run / 'after.json', after)
        save(run / 'receipt.json', {'state': 'native-configured', 'operations': len(operations),
                                   'no_user_memberships_or_passwords_changed': True,
                                   'no_per_user_rancher_provisioning': True,
                                   'browser_and_revocation_acceptance': 'still required'})
        if args.authentik_directory:
            save(args.authentik_directory / 'observer-ready.json',
                 {'version': 1, 'nativeObserverReady': True, 'run': str(run),
                  'policy_sha256': hashlib.sha256(args.policy.read_bytes()).hexdigest()})
        (args.state / 'uncertain.json').unlink()
        print(json.dumps({'applied': True, 'operations': len(operations), 'per_user_sync_daemon': False,
                          'human_membership_changed': False, 'native_browser_acceptance': 'pending'}))


if __name__ == '__main__':
    main()
