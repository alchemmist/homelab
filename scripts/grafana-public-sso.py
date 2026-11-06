#!/usr/bin/env python3
"""Audit first; change only the reviewed Grafana auth environment settings, never the stack."""
import argparse, fcntl, hashlib, json, os, subprocess
from pathlib import Path
NS='cattle-monitoring-system'
DEPLOY='kube-prometheus-stack-grafana'
DESIRED={'GF_AUTH_ANONYMOUS_ENABLED':'false','GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN':'true',
 'GF_AUTH_GENERIC_OAUTH_ALLOWED_GROUPS':'homelab-owner homelab-observer homelab-platform-operator homelab-project-maintainer app-grafana-viewer app-grafana-editor',
 'GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH':"contains(groups[*], 'homelab-owner') && 'GrafanaAdmin' || contains(groups[*], 'app-grafana-editor') && 'Editor' || 'Viewer'"}

def kube(*args):
    return subprocess.check_output(['kubectl','-n',NS,*args],text=True)

def env_plan(d):
    containers=d['spec']['template']['spec']['containers']
    index=next(i for i,c in enumerate(containers) if c['name']=='grafana')
    env=containers[index].get('env',[])
    assert len({e['name'] for e in env})==len(env),'Duplicate env entries'
    lookup={e['name']:e for e in env}
    assert lookup['GF_AUTH_GENERIC_OAUTH_ENABLED']['value']=='true','Native OIDC must already be activated'
    assert lookup['GF_AUTH_GENERIC_OAUTH_CLIENT_ID']['value']=='socrat-grafana'
    assert lookup['GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET']['valueFrom']['secretKeyRef']=={'name':'socrat-authentik-grafana','key':'client-secret'}
    assert lookup['GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT']['value']=='true'
    assert lookup['GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP']['value']=='false'
    assert lookup.get('GF_AUTH_PROXY_ENABLED',{}).get('value','false')=='false'
    updates=[k for k,v in DESIRED.items() if lookup.get(k,{}).get('value')!=v]
    result=[e for e in env if e['name'] not in DESIRED]+[{'name':k,'value':v} for k,v in DESIRED.items()]
    return index,updates,result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args()
    os.umask(0o077)
    root=Path('/var/lib/homelab-grafana-public-sso')
    assert not root.is_symlink()
    root.mkdir(mode=0o700,exist_ok=True)
    assert root.stat().st_uid==0 and root.stat().st_mode&0o077==0
    with (root/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        assert not (root/'uncertain.json').exists(),'Uncertain previous write: inspect retained receipt; no retry'
        d=json.loads(kube('get','deployment',DEPLOY,'-o','json'))
        index,updates,env=env_plan(d)
        plan={'uid':d['metadata']['uid'],'resourceVersion':d['metadata']['resourceVersion'],'changes':{k:DESIRED[k] for k in updates}}
        digest=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if a.apply and updates:
            assert a.approve_plan_hash==digest,'Fresh hash approval required'
            (root/'before.json').write_text(json.dumps(d))
            (root/'uncertain.json').write_text(json.dumps(plan))
            patch=[{'op':'test','path':'/metadata/uid','value':plan['uid']},{'op':'test','path':'/metadata/resourceVersion','value':plan['resourceVersion']},
                   {'op':'replace','path':f'/spec/template/spec/containers/{index}/env','value':env}]
            kube('patch','deployment',DEPLOY,'--type=json','--patch',json.dumps(patch))
            kube('rollout','status','deployment/'+DEPLOY,'--timeout=240s')
            after=json.loads(kube('get','deployment',DEPLOY,'-o','json'))
            assert env_plan(after)[1]==[]
            # Exact pod-template invariants apart from those reviewed env entries.
            old=json.loads(json.dumps(d['spec']['template']));new=json.loads(json.dumps(after['spec']['template']))
            for template in [old,new]:
                c=next(c for c in template['spec']['containers'] if c['name']=='grafana')
                c['env']=[e for e in c['env'] if e['name'] not in DESIRED]
            assert old==new,'Unexpected concurrent pod-template change: stop'
            (root/'after.json').write_text(json.dumps(after));(root/'uncertain.json').unlink()
        print(json.dumps({'plan_hash':digest,'changes':{k:DESIRED[k] for k in updates},'applied':bool(a.apply and updates)}))
if __name__=='__main__':main()
