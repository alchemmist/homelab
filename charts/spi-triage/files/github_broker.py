"""Run next to the existing App secret; export ONLY a repo-scoped one-hour token."""
import base64
import json
import os
import ssl
import time
import urllib.request
from pathlib import Path
import jwt

def request(method,url,token,body=None,context=None):
    req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,method=method,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/merge-patch+json' if method=='PATCH' else 'application/json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(req,context=context,timeout=25) as r:return json.load(r)

def main():
    now=int(time.time());auth=jwt.encode({'iat':now-30,'exp':now+300,'iss':os.environ['GITHUB_APP_ID']},os.environ['GITHUB_PRIVATE_KEY'],algorithm='RS256')
    installation=request('GET','https://api.github.com/repos/alchemmist/homelab/installation',auth)
    if installation.get('suspended_at') or installation['permissions'].get('issues')!='write':raise ValueError('APP_PERMISSION_MISSING')
    grant=request('POST','https://api.github.com/app/installations/'+str(installation['id'])+'/access_tokens',auth,
                  {'repositories':['homelab'],'permissions':{'issues':'write','contents':'read','metadata':'read'}})
    if grant['permissions'].get('pull_requests') or grant['permissions'].get('issues')!='write':raise ValueError('INVALID_TOKEN_SCOPE')
    root=Path('/var/run/secrets/kubernetes.io/serviceaccount')
    context=ssl.create_default_context(cafile=str(root/'ca.crt'))
    request('PATCH','https://kubernetes.default.svc/api/v1/namespaces/automation/secrets/spi-github-installation',(root/'token').read_text(),
            {'data':{'token':base64.b64encode(grant['token'].encode()).decode()},'metadata':{'annotations':{'socrat.alchemmist.xyz/expires-at':grant['expires_at']}}},context)
    print(json.dumps({'component':'spi-token-broker','event':'refresh_ok'}))

if __name__=='__main__':
    try:main()
    except Exception:
        print(json.dumps({'component':'spi-token-broker','event':'refresh_failed'}));raise SystemExit(1)
