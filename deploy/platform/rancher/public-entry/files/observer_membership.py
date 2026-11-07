"""Refresh only the native observer membership cache; never provision users/roles.

Authentik credential can VIEW users/groups only. Rancher service-account can
patch UserAttributes only, not users, roles, workloads, tokens or Secrets.
Wiki uses the same read-only membership snapshot in its native session/token
checks, keeping owner, editor and unlinked machine credentials untouched.
"""
import json
import os
from pathlib import Path
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ORIGIN = 'https://auth.socrat.alchemmist.xyz/api/v3/'
PRINCIPAL = 'genericoidc_group://homelab-observer'
PREFIX = 'genericoidc_user://'
OWNER = '9e33877a-3eaa-4541-98eb-8cdc10088ef6'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def opener(context=None):
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                      urllib.request.HTTPSHandler(context=context or ssl.create_default_context()))


class MembershipReader:
    def __init__(self, token_file, ttl=60):
        self.token_file, self.ttl = Path(token_file), ttl
        self.lock, self.expires = threading.Lock(), 0
        self.users, self.groups = {}, {}
        self.http = opener()

    def rows(self, path):
        token = self.token_file.read_text().strip()
        result = []
        for page in range(1, 201):
            request = urllib.request.Request(ORIGIN + path + '?page_size=100&page=' + str(page),
                                             headers={'Authorization': 'Bearer ' + token})
            try:
                with self.http.open(request, timeout=5) as response:
                    raw = response.read(8 * 1024 * 1024 + 1)
                    if len(raw) > 8 * 1024 * 1024:
                        raise RuntimeError('Membership response bound exceeded')
                    data = json.loads(raw)
            except Exception:
                raise RuntimeError('Membership read unavailable; no stale-access extension') from None
            result.extend(data['results'])
            if not data.get('pagination', {}).get('next'):
                return result
        raise RuntimeError('Incomplete membership pagination')

    def refresh(self):
        with self.lock:
            if time.monotonic() < self.expires:
                return
            groups = self.rows('core/groups/')
            users = self.rows('core/users/')
            if any(not isinstance(g.get('pk'), str) or not isinstance(g.get('name'), str) for g in groups):
                raise RuntimeError('Malformed group snapshot')
            if any(not isinstance(u.get('uuid'), str) or type(u.get('is_active')) is not bool
                   or not isinstance(u.get('groups'), list) for u in users):
                raise RuntimeError('Malformed user snapshot')
            if len({u['uuid'] for u in users}) != len(users) or len({g['pk'] for g in groups}) != len(groups):
                raise RuntimeError('Ambiguous membership snapshot')
            self.groups = {g['pk']: g['name'] for g in groups}
            self.users = {u['uuid']: u for u in users}
            self.expires = time.monotonic() + self.ttl

    def admitted(self, subject, groups):
        self.refresh()
        user = self.users.get(subject)
        return bool(user and user['is_active'] and set(groups) & {self.groups.get(g) for g in user['groups']})


def rancher_plan(users, attributes, authconfig, admitted):
    protected = {OWNER} | {p[len(PREFIX):] for p in authconfig['allowedPrincipalIds'] if p.startswith(PREFIX)}
    by_name = {u['metadata']['name']: u for u in users}
    operations = []
    for attr in attributes:
        meta = attr['metadata']
        user = by_name.get(meta['name'])
        if not user:
            continue
        external = [p[len(PREFIX):] for p in user.get('principalIds', []) if p.startswith(PREFIX)]
        if len(external) != 1 or external[0] in protected:
            continue
        subject = external[0]
        if attr.get('ExtraByProvider', {}).get('genericoidc', {}).get('principalid') != [PREFIX + subject]:
            raise RuntimeError('Native cache identity mismatch')
        cache = attr.get('GroupPrincipals', {}).get('genericoidc')
        if not isinstance(cache, dict) or not isinstance(cache.get('Items'), (list, type(None))):
            raise RuntimeError('Malformed generic OIDC cache')
        old = cache['Items'] or []
        if any(not isinstance(p, dict) or not isinstance(p.get('metadata', {}).get('name'), str) for p in old):
            raise RuntimeError('Malformed cached group principal')
        matching = [p for p in old if p['metadata']['name'] == PRINCIPAL]
        if len(matching) > 1:
            raise RuntimeError('Duplicate cached observer principal')
        wanted = PRINCIPAL in authconfig['allowedPrincipalIds'] and admitted(subject, {'homelab-observer'})
        if bool(matching) == wanted:
            continue
        new = [p for p in old if p['metadata']['name'] != PRINCIPAL]
        if wanted:
            new.append({'metadata': {'name': PRINCIPAL}, 'displayName': 'homelab-observer',
                        'provider': 'genericoidc', 'principalType': 'group', 'memberOf': True})
        patch = [{'op': 'test', 'path': '/metadata/uid', 'value': meta['uid']},
                 {'op': 'test', 'path': '/metadata/resourceVersion', 'value': meta['resourceVersion']},
                 {'op': 'test', 'path': '/ExtraByProvider/genericoidc/principalid', 'value': [PREFIX + subject]},
                 {'op': 'test', 'path': '/GroupPrincipals/genericoidc/Items', 'value': cache['Items']},
                 {'op': 'replace', 'path': '/GroupPrincipals/genericoidc/Items', 'value': new}]
        operations.append((meta['name'], patch))
    return operations


def install_wiki_guard(store):
    path = os.getenv('OBSERVER_IDP_READ_TOKEN_FILE')
    if not path or not getattr(store, 'oidc_enabled', False):
        return
    reader = MembershipReader(path)
    groups = set(json.loads(os.environ['WIKI_OIDC_GROUP_ROLES']))
    issuer = os.environ['WIKI_OIDC_ISSUER']
    def wrap(original):
        def checked(token):
            auth = original(token)
            if not auth or auth['user']['role'] != 'reader' or auth['user']['id'] in store.local_owners:
                return auth
            with store.connect() as db:
                account = db.execute('SELECT subject FROM oidc_accounts WHERE issuer=? AND user_id=?',
                                     (issuer, auth['user']['id'])).fetchone()
            # Existing unlinked machine credentials are not an observer grant.
            if not account:
                return auth
            try:
                return auth if reader.admitted(account['subject'], groups) else None
            except Exception:
                return None
        return checked
    store.session = wrap(store.session)
    store.token_session = wrap(store.token_session)


def reconcile_rancher():
    reader = MembershipReader(os.environ['OBSERVER_IDP_READ_TOKEN_FILE'])
    reader.refresh()  # Complete, validated identity snapshot BEFORE any writes.
    base = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.getenv('KUBERNETES_SERVICE_PORT_HTTPS', '443')
    ca = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
    token = Path('/var/run/secrets/kubernetes.io/serviceaccount/token').read_text().strip()
    http = opener(ssl.create_default_context(cafile=ca))
    prefix = '/apis/management.cattle.io/v3/'
    def call(method, path, body=None):
        request = urllib.request.Request(base + prefix + path, method=method,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json-patch+json'},
            data=None if body is None else json.dumps(body).encode())
        try:
            with http.open(request, timeout=5) as response:
                return json.load(response)
        except Exception:
            raise RuntimeError('Native cache API failed; no blind retry') from None
    def items(path):
        result, cursor = [], ''
        for _ in range(201):
            data = call('GET', path + '?limit=100' + ('&continue=' + urllib.parse.quote(cursor, safe='') if cursor else ''))
            result.extend(data['items']);cursor=data['metadata'].get('continue', '')
            if not cursor:
                return result
        raise RuntimeError('Incomplete native cache pagination')
    operations = rancher_plan(items('users'), items('userattributes'), call('GET', 'authconfigs/genericoidc'), reader.admitted)
    for name, patch in operations:
        call('PATCH', 'userattributes/' + urllib.parse.quote(name, safe=''), patch)
    print(json.dumps({'observer_cache_updates': len(operations), 'users_created': 0, 'roles_modified': 0}))


if __name__ == '__main__':
    try:
        reconcile_rancher()
    except Exception:
        raise SystemExit('Observer membership reconciliation failed safely; inspect native state')
