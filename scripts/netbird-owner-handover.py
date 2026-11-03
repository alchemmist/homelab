#!/usr/bin/env python3
"""Exact-subject native handover, ONLY after the owner personally completes OIDC.
Run on socrat-0; reads the existing private one-day PAT. Default is read-only.
No password, MFA, email lookup/merge, user creation, DB writes or watcher. PUT
once only: upstream atomically demotes the previous owner to admin. No retries.
"""
import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

UUID = '9e33877a-3eaa-4541-98eb-8cdc10088ef6'
CONNECTOR = 'authentik-dbkcr0p119kc73917k1g'
EMAIL = 'anton.ingrish@gmail.com'
TECHNICAL = 'CiQ5MzkxYWJkMy02ZDdhLTRiZDQtOGU2NS1jOWI5MDdkNTJjMDISBWxvY2Fs'
ROOT = Path.home()/'.local/state/netbird-internal-stage/journal'
BASE = 'https://netbird.socrat.alchemmist.xyz/api/'


def subject(uuid=UUID, connector=CONNECTOR):
    a,b=uuid.encode(),connector.encode()
    return base64.b64encode(b'\x0a'+bytes([len(a)])+a+b'\x12'+bytes([len(b)])+b).decode().rstrip('=')


def target_user(users, expected):
    if expected != subject():
        raise ValueError('refusing subject: requires encoded raw owner UUID plus exact connector, never email')
    matches=[u for u in users if u['id']==expected]
    if len(matches)!=1:
        raise ValueError('exact owner identity absent/ambiguous: personally log in first; no email fallback')
    u=matches[0]
    if (u['email']!=EMAIL or u.get('idp_id')!=CONNECTOR or u.get('is_service_user') is not False
        or u.get('is_blocked') is not False or u.get('pending_approval') or u.get('status')!='active'):
        raise ValueError('owner identity fields mismatch; refusing UUID/email substitution')
    stamp=datetime.datetime.fromisoformat(u['last_login'].replace('Z','+00:00'))
    age=datetime.datetime.now(datetime.timezone.utc)-stamp
    if not 0 <= age.total_seconds() < 86400:
        raise ValueError('no recent genuine owner OIDC login evidence')
    return u


def network_snapshot(api, allow_owner_device=False):
    for name in ['setup-keys', 'policies', 'networks']:
        if api(name) != []:
            raise ValueError('unexpected network grants; stop')
    peers = api('peers')
    if not peers:
        return []
    if (not allow_owner_device or len(peers) != 1 or peers[0].get('user_id') != subject()
        or peers[0].get('approval_required') is not False or peers[0].get('login_expired') is not False):
        raise ValueError('only one exact-owner approved personal device may preexist')
    return [{'id': peers[0]['id'], 'user_id': peers[0]['user_id'],
             'approval_required': False, 'login_expired': False}]


def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--subject', required=True)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--confirm-personal-login-and-native-transfer', action='store_true')
    p.add_argument('--allow-existing-owner-device', action='store_true')
    a=p.parse_args()
    if a.subject!=subject():raise ValueError('wrong encoded raw UUID/connector')
    token=json.loads((ROOT/'bootstrap.json').read_text())['personal_access_token']
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # Never forward a private PAT to a redirect destination.
    opener=urllib.request.build_opener(NoRedirect)
    def api(path, body=None):
        request=urllib.request.Request(BASE+path,headers={'Authorization':'Token '+token,'Content-Type':'application/json'},
            data=None if body is None else json.dumps(body).encode(),method='GET' if body is None else 'PUT')
        # Standard trusted TLS, no certificate bypass, redirect or mutation retries.
        with opener.open(request,timeout=20) as r:return json.load(r)
    accounts=api('accounts')
    if len(accounts)!=1 or not accounts[0]['settings']['local_auth_disabled']:raise ValueError('account/local-auth guard failed')
    if accounts[0]['id']!=json.loads((ROOT/'bootstrap-complete.json').read_text())['account_id']:raise ValueError('wrong account')
    network_before = network_snapshot(api, a.allow_existing_owner_device)
    users=api('users');target=target_user(users,a.subject)
    owners=[u for u in users if u['role']=='owner']
    if len(owners)!=1 or owners[0]['id']!=TECHNICAL or owners[0]['email']!='netbird-bootstrap@internal.invalid':
        raise ValueError('expected technical owner only; no replay')
    if target['role']!='user':raise ValueError('unexpected target role')
    if not a.apply:
        print('Exact UUID+connector+email and recent login verified; read-only plan: native user -> owner, technical owner -> admin')
        return
    if not a.confirm_personal_login_and_native_transfer:raise ValueError('personal owner login attestation required')
    journal=ROOT/'stage4-owner-handover-before.json'
    fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'users':users,'account_id':accounts[0]['id']},f)
    api('users/'+urllib.parse.quote(target['id'],safe=''),
        {'role':'owner','auto_groups':target['auto_groups'],'is_blocked':False})
    after=api('users')
    if [u['id'] for u in after if u['role']=='owner']!=[target['id']]:raise ValueError('post-transfer owner mismatch; stop')
    if next(u for u in after if u['id']==TECHNICAL)['role']!='admin':raise ValueError('technical owner was not demoted')
    expected_roles={u['id']:u['role'] for u in users}
    expected_roles.update({target['id']:'owner',TECHNICAL:'admin'})
    if {u['id']:u['role'] for u in after}!=expected_roles:raise ValueError('unexpected other user/role change')
    if network_snapshot(api, a.allow_existing_owner_device) != network_before:
        raise ValueError('unexpected post-transfer network grants/device identity change')
    print('Native owner transfer verified. Technical PAT remains private; existing owner device preserved; no network or other human role granted.')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('BLOCKED: '+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)+'. Inspect private journal; never blindly retry.')
        raise SystemExit(2)
