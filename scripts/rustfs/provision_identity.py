#!/usr/bin/env python3
"""Additive RustFS-only Authentik reconciler, explicit apply, no users/group edits.

Private directory contains credentials.json (AUTHENTIK_API_TOKEN) and persistent
rustfs-client.json. Existing object drift stops, never silently updates grants.
Uses the same provider serializers/flows as the existing configure.py, but does
not invoke that broad identity bootstrap.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import urllib.error
import urllib.parse
import urllib.request

BASE='https://auth.socrat.alchemmist.xyz/api/v3/'
GROUPS=('homelab-owner','homelab-platform-operator')
EXPRESSION='return {"rustfs_policy": ["spi-console-reader"] if ak_is_group_member(request.user, name="homelab-owner") or ak_is_group_member(request.user, name="homelab-platform-operator") else []}'
COLLECTIONS=('core/groups/','flows/instances/','crypto/certificatekeypairs/',
    'propertymappings/provider/scope/','providers/oauth2/','providers/proxy/',
    'core/applications/','policies/bindings/','outposts/instances/')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,response,code,message,headers,newurl):
        if response is not None: response.close()
        raise ValueError('redirect refused')


def main():
    p=argparse.ArgumentParser(); p.add_argument('--private-dir',type=Path,required=True)
    p.add_argument('--apply',action='store_true'); args=p.parse_args()
    spec=importlib.util.spec_from_file_location('bootstrap',Path(__file__).with_name('bootstrap.py'))
    b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
    d=args.private_dir
    st=d.lstat()
    if not d.is_dir() or d.is_symlink() or st.st_uid!=os.getuid() or st.st_mode & 0o077: raise ValueError('private directory required')
    b.private(d/'credentials.json')
    token=json.loads((d/'credentials.json').read_text())['AUTHENTIK_API_TOKEN']
    http=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def api(method,path,body=None):
        if method!='GET' and not args.apply: raise ValueError('writes disabled')
        request=urllib.request.Request(BASE+path,method=method,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with http.open(request,timeout=30) as r:
                data=r.read(2*1024*1024+1)
                if len(data)>2*1024*1024: raise ValueError('oversized inventory')
                return json.loads(data)
        except urllib.error.HTTPError as e:
            e.close(); raise ValueError('identity request failed') from None
    def rows(path):
        result=[]
        for page in range(1,101):
            data=api('GET',path+'?'+urllib.parse.urlencode({'page_size':100,'page':page}))
            result.extend(data['results']); nxt=data['pagination']['next']
            if nxt is None or nxt==0: return result
            if type(nxt) is not int or nxt!=page+1: raise ValueError('pagination mismatch')
        raise ValueError('inventory too large')
    inventory={path:rows(path) for path in COLLECTIONS}
    def one(path,key,value,required=False):
        found=[r for r in inventory[path] if r.get(key)==value]
        if len(found)>1 or required and not found: raise ValueError('missing/duplicate prerequisite')
        return found[0] if found else None
    groups=[one('core/groups/','name',name,True)['pk'] for name in GROUPS]
    flow={slug:one('flows/instances/','slug',slug,True)['pk'] for slug in (
        'default-authentication-flow','default-provider-authorization-explicit-consent',
        'default-provider-authorization-implicit-consent','default-provider-invalidation-flow')}
    cert=one('crypto/certificatekeypairs/','name','authentik Self-signed Certificate',True)['pk']
    mappings=[one('propertymappings/provider/scope/','scope_name',name,True)['pk'] for name in ('openid','profile','email')]
    # Refuse unexplained pre-existing providers when the private journal is lost.
    client_path=d/'rustfs-client.json'
    if client_path.exists():
        b.private(client_path); client=json.loads(client_path.read_text())
    else:
        if one('providers/oauth2/','name','spi-rustfs-native'): raise ValueError('lost private client journal')
        client={'client_id':'spi-rustfs-console','client_secret':secrets.token_urlsafe(48)}
        if args.apply:
            fd=os.open(client_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as out: json.dump(client,out)
    # Inventory-only plan has no mutation, even local client secret persistence.
    if not args.apply:
        print('Plan: native OIDC + two owner/platform-only proxy applications; no memberships/users/roles modified.'); return
    def reconcile(path,key,value,settings):
        old=one(path,key,value)
        if old:
            for k,v in settings.items():
                actual=old.get(k)
                if isinstance(v,list) and all(isinstance(x,(str,int)) for x in v):
                    if sorted(actual or [])!=sorted(v): raise ValueError('existing object drift: '+path)
                elif k=='client_secret':
                    # Some serializers redact secrets. Never rotate implicitly.
                    continue
                elif actual!=v: raise ValueError('existing object drift: '+path)
            return old
        new=api('POST',path,settings); inventory[path].append(new); return new
    scope=reconcile('propertymappings/provider/scope/','name','spi-rustfs-policy',{
        'name':'spi-rustfs-policy','scope_name':'rustfs_policy','expression':EXPRESSION})
    native=reconcile('providers/oauth2/','name','spi-rustfs-native',{
        'name':'spi-rustfs-native','client_type':'confidential','grant_types':['authorization_code'],
        'issuer_mode':'per_provider',**client,
        'authentication_flow':flow['default-authentication-flow'],
        'authorization_flow':flow['default-provider-authorization-explicit-consent'],
        'invalidation_flow':flow['default-provider-invalidation-flow'],
        'property_mappings':mappings+[scope['pk']],'signing_key':cert,
        'redirect_uris':[{'matching_mode':'strict','url':'https://rustfs.socrat.alchemmist.xyz/rustfs/admin/v3/oidc/callback/default'}],
        'include_claims_in_id_token':True,'sub_mode':'user_uuid',
        'access_token_validity':'minutes=5','refresh_token_validity':'hours=1'})
    providers=[]
    apps=[('spi-rustfs-native','RustFS native OIDC',native,'https://rustfs.socrat.alchemmist.xyz/')]
    for slug,host,internal in (
        ('spi-rustfs-console','rustfs.socrat.alchemmist.xyz','http://rustfs.rustfs.svc.cluster.local:9001/'),
        ('spi-evidence','spi-evidence.socrat.alchemmist.xyz','http://rustfs-gateway.rustfs.svc.cluster.local:8080/')):
        provider=reconcile('providers/proxy/','name',slug,{'name':slug,'mode':'forward_single' if slug=='spi-evidence' else 'proxy',
            'authentication_flow':flow['default-authentication-flow'],
            'authorization_flow':flow['default-provider-authorization-implicit-consent'],
            'invalidation_flow':flow['default-provider-invalidation-flow'],
            'external_host':'https://'+host+'/','internal_host':internal,
            'internal_host_ssl_validation':True,'skip_path_regex':'',
            'cookie_domain':host,'intercept_header_auth':False,'basic_auth_enabled':False})
        providers.append(provider['pk']); apps.append((slug,slug,provider,'https://'+host+'/'))
    for slug,name,provider,url in apps:
        app=reconcile('core/applications/','slug',slug,{'name':name,'slug':slug,
            'provider':provider['pk'],'meta_launch_url':url,'policy_engine_mode':'any'})
        bindings=[b for b in inventory['policies/bindings/'] if b.get('target')==app['pk']]
        for binding in bindings:
            if binding.get('group') not in groups or binding.get('policy') or binding.get('user') or binding.get('negate') or not binding.get('enabled') or binding.get('failure_result'):
                raise ValueError('unexpected authorization binding')
        for order,group in enumerate(groups):
            if not any(b.get('group')==group for b in bindings):
                api('POST','policies/bindings/',{'target':app['pk'],'group':group,'order':order,'enabled':True,'failure_result':False})
    outposts=[o for o in inventory['outposts/instances/'] if o.get('managed')=='goauthentik.io/outposts/embedded']
    if len(outposts)!=1: raise ValueError('embedded outpost prerequisite missing')
    outpost=outposts[0]
    # Add only our providers, preserve all existing settings and provider assignments.
    wanted=sorted(set(outpost['providers'])|set(providers))
    if sorted(outpost['providers'])!=wanted:
        api('PATCH','outposts/instances/'+outpost['pk']+'/',{'providers':wanted})
    print('Dedicated applications reconciled; verify discovery S256/client_secret_post and real browser authorization before routes.')

if __name__=='__main__':
    try: main()
    except Exception:
        raise SystemExit('Identity provisioning stopped; private state may be partial. No automatic rollback or existing identity edits.')
