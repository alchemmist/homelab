#!/usr/bin/env python3
"""Bounded Grafana-only empty role-group admission. No human assignments."""
import argparse,datetime,fcntl,hashlib,importlib.machinery,importlib.util,json,os
from pathlib import Path
NAMES=('app-grafana-viewer','app-grafana-editor')
LEGACY=('homelab-owner','homelab-observer','homelab-platform-operator','homelab-project-maintainer')
MARKER={'homelab_app_iam':1}

def require(ok,message):
    if not ok:raise RuntimeError(message)

def build(s):
    groups={g['name']:g for g in s['groups']};ops=[]
    require(len(groups) == len(s['groups']),'Precondition failed; stop and inspect privately')
    for name in NAMES:
        if name not in groups:
            ops.append({'method':'POST','path':'core/groups/','body':{'name':name,'is_superuser':False,'parents':[],'children':[],'users':[],'roles':[],'attributes':MARKER}})
        else:
            g=groups[name]
            require(g['is_superuser'] is False and g['parents'] == [] and (g['roles'] == []) and (g['attributes'] == MARKER),'Precondition failed; stop and inspect privately')
            # Existing preparation groups must be empty; this command grants no one.
            require(g['users'] == [] and g['children'] == [] and (g.get('parent') is None),'Precondition failed; stop and inspect privately')
            require(not any((g['pk'] in other['parents'] for other in s['groups'])),'Precondition failed; stop and inspect privately')
    if ops:return ops
    for slug in ['grafana','public-web-grafana']:
                                                       require(len(apps) == 1,'Precondition failed; stop and inspect privately')
                    require(app['policy_engine_mode'] == 'any','Precondition failed; stop and inspect privately')
                                      require(app['meta_description'] == 'homelab-public-web-v1','Precondition failed; stop and inspect privately')
        bound=[b for b in s['bindings'] if b['target']==app['pk']]
        allowed={groups[n]['pk'] for n in LEGACY+NAMES}
        actual=[]
        for b in bound:
            require(b['group'] in allowed and b['enabled'] and (not b['negate']) and (not b.get('policy')) and (not b.get('user')) and (b['failure_result'] is False),'Precondition failed; stop and inspect privately')
            actual.append(b['group'])
        require(len(set(actual)) == len(actual) and {groups[n]['pk'] for n in LEGACY} <= set(actual),'Precondition failed; stop and inspect privately')
        for n in NAMES:
            if groups[n]['pk'] not in actual:
                ops.append({'method':'POST','path':'policies/bindings/','body':{'target':app['pk'],'group':groups[n]['pk'],'enabled':True,'negate':False,'failure_result':False,'user':None,'policy':None,'order':100}})
    return ops

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    loader=importlib.machinery.SourceFileLoader('web','/usr/local/sbin/homelab-public-web-access');spec=importlib.util.spec_from_loader('web',loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
    api=m.API('/home/alchemmist/.cache/homelab-authentik/credentials.json')
                                                                                                                          require(root.stat().st_uid == 0 and root.stat().st_mode & 63 == 0,'Precondition failed; stop and inspect privately')
    with (root/'lock').open('a') as f:
                                     require(not (root / 'uncertain.json').exists(),'Precondition failed; stop and inspect privately')
        s=m.snapshot(api);ops=build(s)
        digest=hashlib.sha256(json.dumps({'snapshot':s,'ops':ops},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if a.apply and ops:
            require(a.approve_plan_hash == digest,'Precondition failed; stop and inspect privately')
            run=root/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');run.mkdir(mode=0o700)
            (run/'before.json').write_text(json.dumps(s));(root/'uncertain.json').write_text(json.dumps(ops))
            for op in ops:api.call(op['method'],op['path'],op['body'])
            after=m.snapshot(api);remaining=build(after)
            # Group creation and binding creation intentionally require separate plans.
            require(not remaining or all((o['path'] == 'policies/bindings/' for o in remaining)),'Precondition failed; stop and inspect privately')
            (run/'after.json').write_text(json.dumps(after));(root/'uncertain.json').unlink()
        print(json.dumps({'plan_hash':digest,'operations':len(ops),'paths':[o['path'] for o in ops],'applied':bool(a.apply and ops)}))
if __name__=='__main__':main()
