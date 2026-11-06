#!/usr/bin/env python3
"""Bounded Grafana-only empty role-group admission. No human assignments."""
import argparse,datetime,fcntl,hashlib,importlib.machinery,importlib.util,json,os
from pathlib import Path
NAMES=('app-grafana-viewer','app-grafana-editor')
LEGACY=('homelab-owner','homelab-observer','homelab-platform-operator','homelab-project-maintainer')
MARKER={'homelab_app_iam':1}

def build(s):
    groups={g['name']:g for g in s['groups']};ops=[]
    assert len(groups)==len(s['groups'])
    for name in NAMES:
        if name not in groups:
            ops.append({'method':'POST','path':'core/groups/','body':{'name':name,'is_superuser':False,'parents':[],'children':[],'users':[],'roles':[],'attributes':MARKER}})
        else:
            g=groups[name]
            assert g['is_superuser'] is False and g['parents']==[] and g['roles']==[] and g['attributes']==MARKER
            # Existing preparation groups must be empty; this command grants no one.
            assert g['users']==[] and g['children']==[] and g.get('parent') is None
            assert not any(g['pk'] in other['parents'] for other in s['groups'])
    if ops:return ops
    for slug in ['grafana','public-web-grafana']:
        apps=[a for a in s['apps'] if a['slug']==slug];assert len(apps)==1
        app=apps[0];assert app['policy_engine_mode']=='any'
        if slug.startswith('public-'):assert app['meta_description']=='homelab-public-web-v1'
        bound=[b for b in s['bindings'] if b['target']==app['pk']]
        allowed={groups[n]['pk'] for n in LEGACY+NAMES}
        actual=[]
        for b in bound:
            assert b['group'] in allowed and b['enabled'] and not b['negate'] and not b.get('policy') and not b.get('user') and b['failure_result'] is False
            actual.append(b['group'])
        assert len(set(actual))==len(actual) and {groups[n]['pk'] for n in LEGACY}<=set(actual)
        for n in NAMES:
            if groups[n]['pk'] not in actual:
                ops.append({'method':'POST','path':'policies/bindings/','body':{'target':app['pk'],'group':groups[n]['pk'],'enabled':True,'negate':False,'failure_result':False,'user':None,'policy':None,'order':100}})
    return ops

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    loader=importlib.machinery.SourceFileLoader('web','/usr/local/sbin/homelab-public-web-access');spec=importlib.util.spec_from_loader('web',loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
    api=m.API('/home/alchemmist/.cache/homelab-authentik/credentials.json')
    root=Path('/var/lib/homelab-grafana-app-admission');assert not root.is_symlink();root.mkdir(mode=0o700,exist_ok=True);assert root.stat().st_uid==0 and root.stat().st_mode&0o077==0
    with (root/'lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX);assert not (root/'uncertain.json').exists()
        s=m.snapshot(api);ops=build(s)
        digest=hashlib.sha256(json.dumps({'snapshot':s,'ops':ops},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if a.apply and ops:
            assert a.approve_plan_hash==digest
            run=root/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');run.mkdir(mode=0o700)
            (run/'before.json').write_text(json.dumps(s));(root/'uncertain.json').write_text(json.dumps(ops))
            for op in ops:api.call(op['method'],op['path'],op['body'])
            after=m.snapshot(api);remaining=build(after)
            # Group creation and binding creation intentionally require separate plans.
            assert not remaining or all(o['path']=='policies/bindings/' for o in remaining)
            (run/'after.json').write_text(json.dumps(after));(root/'uncertain.json').unlink()
        print(json.dumps({'plan_hash':digest,'operations':len(ops),'paths':[o['path'] for o in ops],'applied':bool(a.apply and ops)}))
if __name__=='__main__':main()
