#!/usr/bin/env python3
"""Create-only, audit-first Authentik gates; does not alter native app roles or users."""
import argparse, datetime, fcntl, hashlib, json, os, re, urllib.request
from pathlib import Path
OWNER='homelab-public-web-v1'

def require(ok, message):
    if not ok: raise ValueError(message)

def unique(rows,key,value):
    matches=[r for r in rows if r.get(key)==value]
    require(len(matches)==1,'Missing/ambiguous reviewed '+key)
    return matches[0]

class API:
    def __init__(self,path):
        self.token=json.loads(Path(path).read_text())['AUTHENTIK_BOOTSTRAP_TOKEN']
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*a,**k): return None
        self.http=urllib.request.build_opener(NoRedirect)
    def call(self,method,path,body=None):
        require(not path.startswith('/') and '://' not in path,'Invalid API path')
        req=urllib.request.Request('https://auth.socrat.alchemmist.xyz/api/v3/'+path,method=method,
          headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},
          data=None if body is None else json.dumps(body).encode())
        with self.http.open(req,timeout=30) as r:
            b=r.read();return json.loads(b) if b else None
    def rows(self,path):
        rows=[]
        for page in range(1,1001):
            d=self.call('GET',path+('&' if '?' in path else '?')+f'page_size=100&page={page}')
            rows.extend(d['results'])
            if not d.get('pagination',{}).get('next'):return rows
        raise ValueError('Pagination exceeded')

def snapshot(api):
    s={k:api.rows(p) for k,p in {'apps':'core/applications/?superuser_full_list=true','providers':'providers/proxy/',
      'groups':'core/groups/','flows':'flows/instances/','bindings':'policies/bindings/',
      'outposts':'outposts/instances/','mfa':'stages/authenticator/validate/','flowbindings':'flows/bindings/'}.items()}
    return s

def plan(s,services):
    flow=unique(s['flows'],'slug','default-authentication-flow')['pk']
    stages={b['stage'].get('pk') if isinstance(b.get('stage'),dict) else b.get('stage') for b in s['flowbindings'] if b['target']==flow}
    validators=[v for v in s['mfa'] if v['pk'] in stages]
    require(validators and all(v.get('not_configured_action')=='configure' for v in validators),'Bound enrollment-required MFA missing')
    authorization=unique(s['flows'],'slug','default-provider-authorization-implicit-consent')['pk']
    invalidation=unique(s['flows'],'slug','default-provider-invalidation-flow')['pk']
    outpost=unique(s['outposts'],'managed','goauthentik.io/outposts/embedded')
    operations=[]
    for slug,svc in services.items():
        require(re.fullmatch(r'[a-z0-9-]+',slug) and svc['host'].endswith('.socrat.alchemmist.xyz'),'Unreviewed hostname')
        require(re.fullmatch(r'http://[a-z0-9.-]+\.svc\.cluster\.local:[0-9]+',svc['upstream']),'Require fixed cluster service upstream')
        if svc.get('machinePathRegex'):
            require(slug=='grafana-mcp' and svc['machinePathRegex']=='^/mcp(?:/|$)' and svc.get('machineAuthentication'),'Unreviewed auth bypass')
        if 'admissionFrom' in svc:
            original=unique(s['apps'],'slug',svc['admissionFrom'])
            require(original['policy_engine_mode']=='any','Native app policy mode drift')
            bindings=[b for b in s['bindings'] if b['target']==original['pk']]
            require(bindings and all(b.get('group') and b.get('enabled') is True and not b.get('negate') and not b.get('policy') and not b.get('user') and b.get('failure_result') is False for b in bindings),'Unsafe native admission bindings')
            groups=sorted({b['group'] for b in bindings})
        else:
            groups=sorted(unique(s['groups'],'name',g)['pk'] for g in svc['groups'])
        # Preserve owner membership; new ordinary admission groups cannot inherit administration.
        for gid in groups:
            g=unique(s['groups'],'pk',gid)
            if g['name']!='homelab-owner':
                require(g.get('is_superuser') is False and g.get('parents')==[] and g.get('roles')==[],'Inherited privilege in admission group')
        name='public-web-'+slug
        settings={'name':name,'mode':'proxy','authentication_flow':flow,'authorization_flow':authorization,
          'invalidation_flow':invalidation,'external_host':'https://'+svc['host']+'/',
          'internal_host':svc['upstream'],'internal_host_ssl_validation':True,
          'cookie_domain':svc['host'],'skip_path_regex':svc.get('machinePathRegex','^$'),
          'intercept_header_auth':False,'basic_auth_enabled':False}
        providers=[p for p in s['providers'] if p['name']==name]
        apps=[a for a in s['apps'] if a['slug']==name]
        require(len(providers)<=1 and len(apps)<=1,'Duplicate managed object')
        provider=providers[0] if providers else None
        app=apps[0] if apps else None
        if provider:
            require(app and app.get('meta_description')==OWNER and app['provider']==provider['pk'],'Refusing orphan/foreign provider adoption')
            require(all(provider.get(k)==v for k,v in settings.items()),'Provider drift: stop and review')
        else:
            require(not app,'Application exists without reviewed provider')
        if app:
            require(app.get('meta_description')==OWNER and app['policy_engine_mode']=='any','Foreign application or policy drift')
            actual=[b for b in s['bindings'] if b['target']==app['pk']]
            require(all(b.get('group') and b.get('enabled') is True and not b.get('negate') and not b.get('policy') and not b.get('user') and b.get('failure_result') is False for b in actual),'Unsafe gate bindings')
            require(sorted(b['group'] for b in actual)==groups,'Admission drift: do not silently expand or remove rights')
            require(provider['pk'] in outpost['providers'],'Outpost assignment drift')
        else:
            operations.append({'slug':name,'provider':settings,'groups':groups})
    return operations,outpost

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',required=True);p.add_argument('--credentials',default='/home/alchemmist/.cache/homelab-authentik/credentials.json')
    p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash')
    p.add_argument('--state',default='/var/lib/homelab-public-web-access')
    a=p.parse_args();os.umask(0o077)
    root=Path(a.state);require(root.is_absolute() and not root.is_symlink(),'Private absolute state directory required')
    if root.exists():require(root.stat().st_uid==os.geteuid() and not root.stat().st_mode&0o077,'Unsafe state directory')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (root/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for r in root.glob('*/receipt.json'):
            require(json.loads(r.read_text())['state'] not in ['applying','uncertain-stop'],'Unreconciled partial run: stop')
        api=API(a.credentials);services=json.loads(Path(a.catalog).read_text());s=snapshot(api);ops,outpost=plan(s,services)
        digest=hashlib.sha256(json.dumps(ops,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if a.apply and ops:
            require(a.approve_plan_hash==digest,'Fresh exact plan approval required')
            d=root/datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%S.%fZ');d.mkdir(mode=0o700)
            (d/'before.json').write_text(json.dumps(s));receipt=d/'receipt.json'
            receipt.write_text(json.dumps({'state':'applying','plan_hash':digest}))
            try:
                ids=list(outpost['providers'])
                for op in ops:
                    provider=api.call('POST','providers/proxy/',op['provider'])
                    app=api.call('POST','core/applications/',{'name':op['slug'],'slug':op['slug'],
                      'provider':provider['pk'],'policy_engine_mode':'any','meta_description':OWNER,
                      'meta_launch_url':op['provider']['external_host'],'meta_group':'Web access'})
                    for order,gid in enumerate(op['groups']):
                        api.call('POST','policies/bindings/',{'target':app['pk'],'group':gid,'order':order,'enabled':True,'failure_result':False})
                    ids.append(provider['pk'])
                current=unique(api.rows('outposts/instances/'),'pk',outpost['pk'])
                require(current['providers']==outpost['providers'],'Concurrent outpost changes: stop')
                api.call('PATCH','outposts/instances/'+outpost['pk']+'/',{'providers':sorted(set(ids))})
                after=snapshot(api);remaining,_=plan(after,services);require(not remaining,'Post-apply readback mismatch')
                (d/'after.json').write_text(json.dumps(after));receipt.write_text(json.dumps({'state':'completed','plan_hash':digest}))
            except Exception:
                receipt.write_text(json.dumps({'state':'uncertain-stop','plan_hash':digest}));raise
        print(json.dumps({'operations':len(ops),'plan_hash':digest,'applied':bool(a.apply and ops),'hosts':[v['host'] for v in services.values()]}))
if __name__=='__main__':main()
