#!/usr/bin/env python3
"""Create exactly two ordinary web-admission groups; never assign humans."""
import argparse,fcntl,hashlib,importlib.machinery,importlib.util,json,os
from pathlib import Path
ROLES={'syncthing-web-admins':'syncthing','uptime-kuma-web-admins':'uptime-kuma'}
def require(ok,message):
    if not ok:raise RuntimeError(message)
def plan(groups):
    ops=[]
    for name,service in ROLES.items():
        rows=[g for g in groups if g['name']==name];require(len(rows)<=1,'Ambiguous role group')
        attrs={'homelab_public_web_role':service}
        if rows:
            g=rows[0]
            require(g['attributes']==attrs and g['is_superuser'] is False and g['parents']==[] and g['children']==[] and g['roles']==[] and isinstance(g['users'],list),'Foreign/inherited role group; stop')
        else:ops.append({'name':name,'attributes':attrs,'is_superuser':False,'parents':[],'children':[],'roles':[],'users':[]})
    return ops

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    loader=importlib.machinery.SourceFileLoader('web','/usr/local/sbin/homelab-public-web-access');spec=importlib.util.spec_from_loader('web',loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
    api=m.API('/home/alchemmist/.cache/homelab-authentik/credentials.json');root=Path('/var/lib/homelab-public-web-role-groups');require(not root.is_symlink(),'Unsafe state path');root.mkdir(mode=0o700,exist_ok=True)
    require(root.stat().st_uid==0 and not root.stat().st_mode&0o077,'Unsafe state ownership')
    with (root/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);require(not (root/'uncertain.json').exists(),'Uncertain previous write')
        before=api.rows('core/groups/');ops=plan(before)
        digest=hashlib.sha256(json.dumps({'groups':before,'ops':ops},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if a.apply and ops:
            require(a.approve_plan_hash==digest,'Fresh plan hash approval required')
            (root/'before.json').write_text(json.dumps(before));(root/'uncertain.json').write_text(json.dumps(ops))
            for op in ops:api.call('POST','core/groups/',op)
            after=api.rows('core/groups/');require(not plan(after),'Creation not confirmed')
            require(all(g in after for g in before),'Existing groups/memberships changed')
            (root/'after.json').write_text(json.dumps(after));(root/'uncertain.json').unlink()
        print(json.dumps({'operations':len(ops),'plan_hash':digest,'applied':bool(a.apply and ops)}))
if __name__=='__main__':main()
