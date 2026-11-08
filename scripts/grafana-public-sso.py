#!/usr/bin/env python3
"""Audit first; change only the reviewed Grafana auth environment settings, never the stack."""
import argparse, fcntl, hashlib, json, os, subprocess
from pathlib import Path
NS='cattle-monitoring-system'
DEPLOY='kube-prometheus-stack-grafana'
DESIRED={'GF_AUTH_ANONYMOUS_ENABLED':'false','GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN':'true',
 'GF_AUTH_GENERIC_OAUTH_ALLOWED_GROUPS':'homelab-owner homelab-observer homelab-platform-operator homelab-project-maintainer app-grafana-viewer app-grafana-editor',
 'GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH':"contains(groups[*], 'homelab-owner') && 'GrafanaAdmin' || contains(groups[*], 'app-grafana-editor') && 'Editor' || (contains(groups[*], 'homelab-observer') || contains(groups[*], 'homelab-platform-operator') || contains(groups[*], 'homelab-project-maintainer') || contains(groups[*], 'app-grafana-viewer')) && 'Viewer' || ''"}

def require(ok,message):
    if not ok:raise RuntimeError(message)

def kube(*args):
    return subprocess.check_output(['kubectl','-n',NS,*args],text=True)

def env_plan(d):
    containers=d['spec']['template']['spec']['containers']
    index=next(i for i,c in enumerate(containers) if c['name']=='grafana')
    env=containers[index].get('env',[])
    require(len({e['name'] for e in env}) == len(env),'Duplicate env entries')
    lookup={e['name']:e for e in env}
    require(lookup['GF_AUTH_GENERIC_OAUTH_ENABLED']['value'] == 'true','Native OIDC must already be activated')
    require(lookup['GF_AUTH_GENERIC_OAUTH_CLIENT_ID']['value'] == 'socrat-grafana','Precondition failed; stop and inspect privately')
    require(lookup['GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET']['valueFrom']['secretKeyRef'] == {'name': 'socrat-authentik-grafana', 'key': 'client-secret'},'Precondition failed; stop and inspect privately')
    require(lookup['GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT']['value'] == 'true','Precondition failed; stop and inspect privately')
    require(lookup['GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP']['value'] == 'false','Precondition failed; stop and inspect privately')
    require(lookup.get('GF_AUTH_PROXY_ENABLED', {}).get('value', 'false') == 'false','Precondition failed; stop and inspect privately')
    legacy_groups='homelab-owner homelab-observer homelab-platform-operator homelab-project-maintainer'
    previous_role="contains(groups[*], 'homelab-owner') && 'GrafanaAdmin' || contains(groups[*], 'app-grafana-editor') && 'Editor' || 'Viewer'"
    legacy_role="contains(groups[*], 'homelab-owner') && 'GrafanaAdmin' || 'Viewer'"
    require(lookup['GF_AUTH_GENERIC_OAUTH_ALLOWED_GROUPS']['value'] in (legacy_groups,DESIRED['GF_AUTH_GENERIC_OAUTH_ALLOWED_GROUPS']),'Unreviewed native admission; stop')
    require(lookup['GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH']['value'] in (legacy_role,previous_role,DESIRED['GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH']),'Unreviewed native role mapping; stop')
    updates=[k for k,v in DESIRED.items() if lookup.get(k,{}).get('value')!=v]
    result=[e for e in env if e['name'] not in DESIRED]+[{'name':k,'value':v} for k,v in DESIRED.items()]
    return index,updates,result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args()
    os.umask(0o077)
    root=Path('/var/lib/homelab-grafana-public-sso')
    require(not root.is_symlink(),'Precondition failed; stop and inspect privately')
    root.mkdir(mode=0o700,exist_ok=True)
    require(root.stat().st_uid == 0 and root.stat().st_mode & 63 == 0,'Precondition failed; stop and inspect privately')
    with (root/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        require(not (root / 'uncertain.json').exists(),'Uncertain previous write: inspect retained receipt; no retry')
        d=json.loads(kube('get','deployment',DEPLOY,'-o','json'))
        index,updates,env=env_plan(d)
        plan={'uid':d['metadata']['uid'],'resourceVersion':d['metadata']['resourceVersion'],'changes':{k:DESIRED[k] for k in updates}}
        digest=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if a.apply and updates:
            require(a.approve_plan_hash == digest,'Fresh hash approval required')
            (root/'before.json').write_text(json.dumps(d))
            (root/'uncertain.json').write_text(json.dumps(plan))
            patch=[{'op':'test','path':'/metadata/uid','value':plan['uid']},{'op':'test','path':'/metadata/resourceVersion','value':plan['resourceVersion']},
                   {'op':'replace','path':f'/spec/template/spec/containers/{index}/env','value':env}]
            kube('patch','deployment',DEPLOY,'--type=json','--patch',json.dumps(patch))
            kube('rollout','status','deployment/'+DEPLOY,'--timeout=240s')
            after=json.loads(kube('get','deployment',DEPLOY,'-o','json'))
            require(env_plan(after)[1] == [],'Precondition failed; stop and inspect privately')
            # Exact pod-template invariants apart from those reviewed env entries.
            old=json.loads(json.dumps(d['spec']['template']));new=json.loads(json.dumps(after['spec']['template']))
            for template in [old,new]:
                c=next(c for c in template['spec']['containers'] if c['name']=='grafana')
                c['env']=[e for e in c['env'] if e['name'] not in DESIRED]
            require(old == new,'Unexpected concurrent pod-template change: stop')
            (root/'after.json').write_text(json.dumps(after));(root/'uncertain.json').unlink()
        print(json.dumps({'plan_hash':digest,'changes':{k:DESIRED[k] for k in updates},'applied':bool(a.apply and updates)}))
if __name__=='__main__':main()
