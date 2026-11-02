#!/usr/bin/env python3
"""One-shot private v0.82.0 bootstrap on the owner Kubernetes host.

Run with Python on socrat-0, not against a public endpoint. Requires fresh,
decryption-verified encrypted backups in the private runtime journal. Never
retries a mutation. Local auth stays enabled until a real owner OIDC login and
native API ownership transfer; this tool does not perform that transfer.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path.home() / '.local/state/netbird-internal-stage'
KUBE = ['env', 'K3S_CONFIG_FILE=/dev/null', 'kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml', '-n', 'netbird-pilot']


def require(ok, message):
    if not ok:
        raise ValueError(message)


def private(path, data):
    require(not path.is_symlink(), 'private path is a symlink')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f)


def evidence(root, name):
    data = json.loads((root / 'journal' / (name + '.evidence.json')).read_text())
    age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(data['created_at'])
    require(data['encrypted'] is True and data['decrypt_verified'] is True and
            0 <= age.total_seconds() < 3600 and Path(data['archive']).is_file(), 'fresh verified encrypted backup required')


def settings_body(account):
    settings = dict(account['settings'])
    settings.update(jwt_groups_enabled=True, jwt_groups_claim_name='groups',
                    jwt_allow_groups=['netbird-pilot-login'], groups_propagation_enabled=True,
                    peer_login_expiration_enabled=True, peer_login_expiration=28800,
                    regular_users_view_blocked=True)
    for key in ('embedded_idp_enabled', 'local_auth_disabled'):
        settings.pop(key, None)
    return {'settings': settings}


def default_policy(policies):
    require(isinstance(policies, list) and len(policies) == 1, 'expected only native Default policy')
    p = policies[0]
    require(p['name'] == 'Default' and p['enabled'] is True and len(p['rules']) == 1,
            'unexpected default policy')
    rule = p['rules'][0]
    require(rule['action'] == 'accept' and rule['protocol'] == 'all' and rule['bidirectional'] is True,
            'unexpected default rule')
    require([g['name'] for g in rule['sources']] == ['All'] and
            [g['name'] for g in rule['destinations']] == ['All'], 'unexpected default groups')
    return p['id']


def run(command):
    return subprocess.check_output(KUBE + command, stderr=subprocess.DEVNULL)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['bootstrap', 'configure-idp'])
    args = parser.parse_args()
    evidence(ROOT, 'netbird-pre-stage2')
    journal = ROOT / 'journal'
    token = None
    process = None

    def api(method, path, body=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Token ' + token
        req = urllib.request.Request('http://127.0.0.1:18081/api/' + path, method=method,
                                     headers=headers, data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                result = response.read()
                return json.loads(result) if result else None
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise ValueError('NetBird API rejected ' + method + ' ' + path + ' status=' + str(code)) from None

    def forward():
        nonlocal process
        # Poll reads only; never retry setup or another mutation.
        for _ in range(45):
            pods = json.loads(run(['get', 'pods', '-l', 'app=netbird-server', '-o', 'json']))['items']
            running = [p for p in pods if not p['metadata'].get('deletionTimestamp') and p['status']['phase'] == 'Running']
            if len(running) == 1:
                break
            time.sleep(1)
        else:
            raise ValueError('no unique running server')
        process = subprocess.Popen(KUBE + ['port-forward', '--address=127.0.0.1',
                                          'pod/' + running[0]['metadata']['name'], '18081:80'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            try:
                return api('GET', 'instance')
            except urllib.error.URLError:
                time.sleep(1)
        raise ValueError('private port-forward unavailable')

    enabled = False
    try:
        if args.action == 'bootstrap':
            require(not (journal / 'bootstrap.json').exists(), 'bootstrap journal exists; no replay')
            run(['set', 'env', 'deploy/server', 'NB_SETUP_PAT_ENABLED=true'])
            enabled = True
            # Wait for deployment's old pod to be removed, including Recreate rollout.
            time.sleep(4)
            status = forward()
            require(status.get('setup_required') is True, 'instance already claimed')
            password = secrets.token_urlsafe(48)
            private(journal / 'bootstrap-password.json', {'email': 'netbird-bootstrap@internal.invalid', 'password': password})
            result = api('POST', 'setup', {'email': 'netbird-bootstrap@internal.invalid', 'password': password,
                        'name': 'Private technical bootstrap', 'create_pat': True, 'pat_expire_in': 1})
            token = result.get('personal_access_token')
            require(isinstance(token, str) and token, 'setup did not return PAT; stop')
            private(journal / 'bootstrap.json', result)
            accounts = api('GET', 'accounts')
            require(len(accounts) == 1, 'expected one account')
            require(api('GET', 'peers') == [] and api('GET', 'setup-keys') == [], 'unexpected peers/setup keys')
            policy_id = default_policy(api('GET', 'policies'))
            api('DELETE', 'policies/' + policy_id)
            require(api('GET', 'policies') == [], 'policies not empty')
            desired = settings_body(accounts[0])
            api('PUT', 'accounts/' + accounts[0]['id'], desired)
            actual = api('GET', 'accounts')[0]['settings']
            for key in ('jwt_groups_enabled', 'jwt_groups_claim_name', 'jwt_allow_groups',
                        'groups_propagation_enabled', 'peer_login_expiration_enabled',
                        'peer_login_expiration', 'regular_users_view_blocked'):
                require(actual[key] == desired['settings'][key], 'account settings drift')
            private(journal / 'bootstrap-complete.json', {'account_id': accounts[0]['id'], 'policies': [],
                    'peers': [], 'setup_keys': [], 'local_auth_kept_private': True})
            print('Private bootstrap complete; empty peers/setup keys/policies; account admission configured')
        else:
            evidence(ROOT, 'authentik-pre-stage2')
            token = json.loads((journal / 'bootstrap.json').read_text())['personal_access_token']
            forward()
            require(api('GET', 'identity-providers') == [], 'identity provider already exists; no replay')
            authroot = Path.home() / '.cache/homelab-authentik'
            runtime = json.loads((authroot / 'netbird-oidc-runtime.json').read_text())
            require(json.loads((authroot / 'netbird-oidc-journal.json').read_text())['status'] == 'reconciled', 'Authentik not reconciled')
            body = dict(name='Authentik', type='authentik', issuer='https://auth.socrat.alchemmist.xyz/application/o/netbird-pilot/', **runtime)
            result = api('POST', 'identity-providers', body)
            require(len(api('GET', 'identity-providers')) == 1, 'IdP count drift')
            private(journal / 'identity-provider.json', {'id': result['id'], 'type': result['type'], 'issuer': result['issuer']})
            print('Authentik connector configured; real owner login/transfer not yet accepted')
    finally:
        if process:
            process.terminate()
            process.wait(timeout=10)
        if enabled:
            run(['set', 'env', 'deploy/server', 'NB_SETUP_PAT_ENABLED=false'])
            print('NB_SETUP_PAT_ENABLED=false restored')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError):
        print('BLOCKED: stage2 stopped; inspect private journal; no blind write retries')
        raise SystemExit(2)
