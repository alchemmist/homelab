#!/usr/bin/env python3
"""Read-only compatibility audit: external Authentik proxy creation is retired."""
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
    require(not services, 'External Authentik proxy gates are retired; use native service authentication')
    return [], unique(s['outposts'],'managed','goauthentik.io/outposts/embedded')

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
        print(json.dumps({'operations':len(ops),'plan_hash':digest,'applied':bool(a.apply and ops),'hosts':[v['host'] for v in services.values()]}))
if __name__=='__main__':main()
