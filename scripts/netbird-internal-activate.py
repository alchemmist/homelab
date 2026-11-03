#!/usr/bin/env python3
"""Historical first-activation plan; hash-approved apply after real OIDC refresh.

Not a replay/reconciliation command after the single-gateway migration. Existing
policy/state drift is deliberately rejected rather than overwritten.

Run on socrat-0 with private bootstrap PAT/journal. Never invent a JWT group or
modify human accounts, WireGuard, SSH, setup keys, router identities, or defaults.
After any apply error inspect the exclusive journal; no blind mutation retries.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import urllib.request

ROOT = Path.home()/'.local/state/netbird-internal-stage/journal'
BASE = 'https://netbird.socrat.alchemmist.xyz/api/'


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--approve-plan-hash')
    args = parser.parse_args()
    compiler = runpy.run_path(str(Path(__file__).with_name('netbird-internal-network.py')))
    identity = runpy.run_path(str(ROOT.parent/'owner-handover-v2.py'))
    token = json.loads((ROOT/'bootstrap.json').read_text())['personal_access_token']
    state = json.loads((ROOT/'internal-network-stage.json').read_text())
    if state['state'] != 'internal-resources-ready-await-genuine-admin-JWT':
        raise ValueError('unexpected stage or replay')
    if not (ROOT/'internal-network-enrollment-retired.json').is_file():
        raise ValueError('enrollment keys and Secrets must be retired first')

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    opener = urllib.request.build_opener(NoRedirect)

    def api(method, endpoint, body=None):
        req = urllib.request.Request(BASE+endpoint, method=method,
            headers={'Authorization': 'Token '+token, 'Content-Type': 'application/json'},
            data=None if body is None else json.dumps(body).encode())
        with opener.open(req, timeout=15) as response:
            return json.load(response)

    users = api('GET', 'users')
    identity['target_user'](users, identity['subject']())
    if [u['id'] for u in users if u['role'] == 'owner'] != [identity['subject']()]:
        raise ValueError('native owner identity mismatch')
    policies = api('GET', 'policies')
    if {p['id'] for p in policies} != {state['ssh_policy']}:
        raise ValueError('unexpected policy drift')
    groups = api('GET', 'groups')
    admin_id = compiler['genuine_admin_group'](groups)
    group = api('GET', 'groups/'+admin_id)
    members = {p['id'] if isinstance(p, dict) else p for p in group.get('peers', [])}
    peers = api('GET', 'peers')
    owner_peers = {p['id'] for p in peers if p.get('user_id') == identity['subject']()
                   and not p.get('approval_required') and not p.get('login_expired')}
    if not members or not members.issubset(owner_peers):
        raise ValueError('admin JWT members must be genuinely admitted exact-owner devices only')
    if {n['id'] for n in api('GET', 'networks')} != {n['id'] for n in state['networks'].values()}:
        raise ValueError('network drift')
    plan = []
    for host, (name, addresses) in compiler['NETWORKS'].items():
        network = state['networks'][host]
        resources = api('GET', 'networks/'+network['id']+'/resources')
        if {r['address'] for r in resources} != set(addresses):
            raise ValueError('resource scope drift')
        routers = api('GET', 'networks/'+network['id']+'/routers')
        if (len(routers) != 1 or routers[0]['peer'] != state['peers'][host]['id']
            or not routers[0]['enabled'] or not routers[0]['masquerade']):
            raise ValueError('router/return-path drift')
        for resource in resources:
            if not resource['enabled'] or resource['type'] != 'host' or resource.get('groups'):
                raise ValueError('resource enabled/type/group drift')
            plan.append({'address': resource['address'],
                         'body': compiler['policy_body'](admin_id, resource['id'])})
    plan.sort(key=lambda p: p['address'])
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    print(json.dumps({'plan_hash': digest, 'admin_devices': len(members),
                      'destinations': [p['address'] for p in plan], 'writes': len(plan)}), flush=True)
    if not args.apply:
        return
    if args.approve_plan_hash != digest:
        raise ValueError('approved current plan hash required')
    dest = ROOT/'internal-network-activation-before.json'
    fd = os.open(dest, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'plan': plan, 'plan_hash': digest, 'policies_before': policies,
                   'roles_before': {u['id']: u['role'] for u in users}}, f)
    created = []
    for item in plan:
        response = api('POST', 'policies', item['body'])
        created.append(response['id'])
        # Record each successful create before any subsequent mutation.
        p = ROOT/'internal-network-activation-progress.json'
        p.write_text(json.dumps({'created_policy_ids': created})); p.chmod(0o600)
        rule = response['rules'][0]
        source_ids = {g['id'] if isinstance(g, dict) else g for g in rule['sources']}
        if (source_ids != {admin_id} or rule['protocol'] != 'all' or rule['bidirectional']
            or rule['destinationResource'] != item['body']['rules'][0]['destinationResource']):
            raise ValueError('native policy readback mismatch; inspect journal, no retry')
    after = api('GET', 'policies')
    if {p['id'] for p in after} != {state['ssh_policy'], *created}:
        raise ValueError('unexpected policies after activation')
    if {u['id']: u['role'] for u in api('GET', 'users')} != {u['id']: u['role'] for u in users}:
        raise ValueError('unexpected role changes')
    fd = os.open(ROOT/'internal-network-activation-complete.json', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'policy_ids': created, 'plan_hash': digest, 'genuine_jwt_source': True,
                   'exact_node_prefixes': [p['address'] for p in plan]}, f)
    print('Native admin-only WG node policies created and read back. Real Mac routing/access acceptance still required.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('BLOCKED: '+(str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
        raise SystemExit(2)
