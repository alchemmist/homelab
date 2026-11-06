#!/usr/bin/env python3
"""Preserve existing Kuma DB credentials; detach only an obsolete GitOps tracking tag."""
import argparse,fcntl,hashlib,json,os,subprocess
from pathlib import Path
NS='uptime-kuma';NAME='uptime-kuma-db';TRACK='uptime-kuma:/Secret:uptime-kuma/uptime-kuma-db'
def require(ok,message):
    if not ok:raise RuntimeError(message)
def get(kind,name,ns=NS):return json.loads(subprocess.check_output(['kubectl','-n',ns,'get',kind,name,'-o','json']))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    root=Path('/var/lib/homelab-kuma-credential-ownership');require(not root.is_symlink(),'Unsafe state path');root.mkdir(mode=0o700,exist_ok=True)
    require(root.stat().st_uid==0 and not root.stat().st_mode&0o077,'Unsafe state ownership')
    with (root/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);require(not (root/'uncertain.json').exists(),'Uncertain prior write')
        before=get('secret',NAME);meta=before['metadata'];ann=meta.get('annotations',{})
        require(ann.get('meta.helm.sh/release-name')=='uptime-kuma' and ann.get('meta.helm.sh/release-namespace')==NS,'Foreign secret')
        require(set(before['data'])=={'password','root-password'} and all(before['data'].values()),'Incomplete existing credentials')
        if 'argocd.argoproj.io/tracking-id' not in ann and ann.get('helm.sh/resource-policy')=='keep':print(json.dumps({'operations':0,'applied':False}));return
        require(ann.get('argocd.argoproj.io/tracking-id')==TRACK,'Foreign tracking owner')
        app=get('applications.argoproj.io','uptime-kuma','argocd')
        require(app['spec']['syncPolicy']['automated']['prune'] is False,'Never prune credentials')
        resource=next(r for r in app['status']['resources'] if r['kind']=='Secret' and r['name']==NAME)
        require(resource.get('requiresPruning') is True,'Desired manifests still manage the credential: stop')
        context={'uid':meta['uid'],'resourceVersion':meta['resourceVersion'],'source_revision':app['status']['sync']['revision'],'credential_hash':hashlib.sha256(json.dumps(before['data'],sort_keys=True).encode()).hexdigest()}
        digest=hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
        if a.apply:
            require(a.approve_plan_hash==digest,'Fresh plan hash required')
            (root/'before.json').write_text(json.dumps(before));(root/'uncertain.json').write_text(json.dumps(context))
            patch=[{'op':'test','path':'/metadata/uid','value':meta['uid']},{'op':'test','path':'/metadata/resourceVersion','value':meta['resourceVersion']},
                   {'op':'remove','path':'/metadata/annotations/argocd.argoproj.io~1tracking-id'},
                   {'op':'add','path':'/metadata/annotations/helm.sh~1resource-policy','value':'keep'}]
            subprocess.run(['kubectl','-n',NS,'patch','secret',NAME,'--type=json','--patch-file=/dev/stdin'],input=json.dumps(patch),text=True,check=True,capture_output=True)
            after=get('secret',NAME)
            require(after['metadata']['uid']==meta['uid'] and after['data']==before['data'],'Credential data changed; stop')
            require(after['metadata']['annotations'].get('argocd.argoproj.io/tracking-id') is None and after['metadata']['annotations'].get('helm.sh/resource-policy')=='keep','Ownership update not confirmed')
            (root/'after.json').write_text(json.dumps(after));(root/'uncertain.json').unlink()
        print(json.dumps({'operations':1,'plan_hash':digest,'applied':a.apply,'credential_data_replacement':False}))
if __name__=='__main__':main()
