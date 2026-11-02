#!/usr/bin/env python3
"""Narrow owner-only 3x-ui Authentik gateway reconciliation, not native SSO.
No users, native panel database, password, MFA stage or VPN runtime is changed.
An existing provider/application requires the protected UUID/PK journal; never
silently adopt by name. Initial creation needs private xui-panel-launch.json.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('config', type=Path)
    parser.add_argument('--action', choices=['check', 'apply'], default='check')
    parser.add_argument('--public-edge', choices=['109.173.40.247', '176.98.185.59'])
    args = parser.parse_args()
    if args.public_edge:
        original = socket.getaddrinfo
        socket.getaddrinfo = lambda h, *a, **kw: original(args.public_edge if h == 'auth.socrat.alchemmist.xyz' else h, *a, **kw)
    config = json.loads(args.config.read_text())
    runtime = json.loads((args.root/'credentials.json').read_text())
    def api(method, path, payload=None):
        req = urllib.request.Request('https://auth.socrat.alchemmist.xyz/api/v3/'+path, method=method,
            headers={'Authorization':'Bearer '+runtime['AUTHENTIK_BOOTSTRAP_TOKEN'], 'Content-Type':'application/json'},
            data=json.dumps(payload).encode() if payload is not None else None)
        with urllib.request.urlopen(req, timeout=45) as r:
            body=r.read()
            return json.loads(body) if body else None
    def unique(path, field, value):
        rows=[r for r in api('GET',path+'?page_size=100&superuser_full_list=true')['results'] if r[field]==value]
        if len(rows)>1: raise RuntimeError('Ambiguous managed object')
        return rows[0] if rows else None
    def save(path, value):
        with open(path,'w',opener=lambda p,f:os.open(p,f,0o600)) as f: json.dump(value,f,indent=2)
        path.chmod(0o600)
    if api('GET','admin/version/')['version_current']!='2026.8.5':
        raise RuntimeError('Unreviewed Authentik version')
    journal_path=args.root/'xui-panel-journal.json'
    journal=json.loads(journal_path.read_text()) if journal_path.exists() else None
    provider=unique('providers/proxy/','name',config['providerName'])
    app=unique('core/applications/','slug',config['slug'])
    if provider or app:
        if not journal or not provider or not app or provider['pk']!=journal['providerPk'] or app['pk']!=journal['applicationPk'] or app['provider']!=provider['pk']:
            raise RuntimeError('Managed identity mismatch; protected journal required')
    elif journal: raise RuntimeError('Journal exists but managed objects are missing')
    owner=unique('core/groups/','name',config['ownerGroup'])
    if not owner: raise RuntimeError('Reviewed owner group is missing')
    bindings=[] if not app else [b for b in api('GET','policies/bindings/?page_size=1000')['results'] if b['target']==app['pk']]
    if len(bindings)>1 or any(b.get('group')!=owner['pk'] or b.get('user') or b.get('policy') or b.get('negate') or b.get('failure_result') or not b['enabled'] for b in bindings):
        raise RuntimeError('Unexpected app admission binding; do not silently remove or adopt it')
    launch=json.loads((args.root/'xui-panel-launch.json').read_text())['url']
    parsed=urllib.parse.urlparse(launch)
    if parsed.scheme!='https' or parsed.netloc!='vpn.alchemmist.xyz' or parsed.query or parsed.fragment:
        raise RuntimeError('Launch URL must be the reviewed HTTPS panel path')
    flows={f['slug']:f['pk'] for f in api('GET','flows/instances/?page_size=100')['results']}
    desired={'name':config['providerName'],'mode':config['mode'],'external_host':config['externalHost'],
        'internal_host':'','internal_host_ssl_validation':True,'cookie_domain':'vpn.alchemmist.xyz',
        'skip_path_regex':'','intercept_header_auth':False,'basic_auth_enabled':False,
        'authentication_flow':flows['default-authentication-flow'],
        'authorization_flow':flows['default-provider-authorization-implicit-consent'],
        'invalidation_flow':flows['default-provider-invalidation-flow'],
        'access_token_validity':config['accessValidity'],'refresh_token_validity':config['refreshValidity']}
    scopes=api('GET','propertymappings/provider/scope/?page_size=100')['results']
    offline=[s['pk'] for s in scopes if s['managed']=='goauthentik.io/providers/oauth2/scope-offline_access']
    if len(offline)!=1: raise RuntimeError('Reviewed offline-access mapping missing')
    defaults={'ak_proxy','email','entitlements','openid','profile'}
    mappings=provider['property_mappings'] if provider else [s['pk'] for s in scopes if s['scope_name'] in defaults]
    desired['property_mappings']=list(dict.fromkeys(mappings+offline))
    icon=config['iconSha256'][:12]
    app_fields={'name':config['name'],'slug':config['slug'],'meta_launch_url':launch,
        'meta_icon':'https://vpn.alchemmist.xyz/-/xui-brand/'+icon+'.png',
        'meta_description':'Owner-only MFA gateway; native panel login remains. VPN subscriptions and traffic are separate.',
        'group':'Socrat','policy_engine_mode':'any'}
    embedded=[o for o in api('GET','outposts/instances/?page_size=100')['results'] if o.get('managed')=='goauthentik.io/outposts/embedded']
    if len(embedded)!=1: raise RuntimeError('Expected one embedded outpost')
    outpost=embedded[0]
    if journal and journal['outpostPk']!=outpost['pk']: raise RuntimeError('Outpost identity mismatch')
    changes=not provider or not app or len(bindings)!=1 or any(provider.get(k)!=v for k,v in desired.items()) or any(app.get(k)!=v for k,v in app_fields.items()) or provider['pk'] not in outpost['providers']
    if args.action=='check':
        if changes: raise RuntimeError('Gateway configuration is not reconciled')
        print('Owner-only gateway already reconciled; no identity or VPN changes')
        return
    if not changes:
        print('Owner-only gateway already reconciled; changed=false')
        return
    save(args.root/'xui-panel-before-reconcile.json', {'provider':provider,'application':app,'bindings':bindings,'outpost':outpost})
    provider=api('PATCH','providers/proxy/'+str(provider['pk'])+'/',desired) if provider else api('POST','providers/proxy/',desired)
    app_fields['provider']=provider['pk']
    app=api('PATCH','core/applications/'+config['slug']+'/',app_fields) if app else api('POST','core/applications/',app_fields)
    binding=bindings[0] if bindings else api('POST','policies/bindings/',{'target':app['pk'],'group':owner['pk'],'order':0,'enabled':True,'failure_result':False})
    if provider['pk'] not in outpost['providers']:
        api('PATCH','outposts/instances/'+outpost['pk']+'/',{'providers':outpost['providers']+[provider['pk']]})
    save(journal_path,{'providerPk':provider['pk'],'applicationPk':app['pk'],'bindingPk':binding['pk'],'outpostPk':outpost['pk']})
    print('Owner-only gateway reconciled; changed=true; native login remains')


if __name__=='__main__':
    main()
