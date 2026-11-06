#!/usr/bin/env python3
"""Retire only the owned, unused Grafana proxy app after native SSO acceptance."""
import argparse,fcntl,hashlib,importlib.machinery,importlib.util,json,os,subprocess
from pathlib import Path

def require(ok,message):
    if not ok:raise RuntimeError(message)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    loader=importlib.machinery.SourceFileLoader('web','/usr/local/sbin/homelab-public-web-access');spec=importlib.util.spec_from_loader('web',loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
    api=m.API('/home/alchemmist/.cache/homelab-authentik/credentials.json')
    root=Path('/var/lib/homelab-retire-grafana-proxy');require(not root.is_symlink(),'Unsafe state path');root.mkdir(mode=0o700,exist_ok=True)
    require(root.stat().st_uid==0 and not root.stat().st_mode&0o077,'Unsafe state ownership')
    with (root/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);require(not (root/'uncertain.json').exists(),'Uncertain previous write; stop')
        d=json.loads(subprocess.check_output(['kubectl','-n','cattle-monitoring-system','get','deploy','kube-prometheus-stack-grafana','-o','json']))
        env={e['name']:e.get('value') for e in next(c for c in d['spec']['template']['spec']['containers'] if c['name']=='grafana')['env']}
        require(env['GF_AUTH_ANONYMOUS_ENABLED']=='false' and env['GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN']=='true','Native policy not active')
        ingress=json.loads(subprocess.check_output(['kubectl','-n','identity','get','ingress','public-web-grafana','-o','json']))
        require(ingress['spec']['rules'][0]['http']['paths'][0]['backend']['service']['name']=='public-web-grafana-proxy','Old gate still routed')
        s=m.snapshot(api);apps=[x for x in s['apps'] if x['slug']=='public-web-grafana'];providers=[x for x in s['providers'] if x['name']=='public-web-grafana']
        if not apps and not providers:print(json.dumps({'operations':0,'applied':False}));return
        require(len(apps)==len(providers)==1,'Ambiguous owned gate')
        catalog={'grafana':{'host':'grafana.socrat.alchemmist.xyz','upstream':'http://kube-prometheus-stack-grafana.cattle-monitoring-system.svc.cluster.local:80','admissionFrom':'grafana'}}
        ops,outpost=m.plan(s,catalog);require(not ops,'Owned gate drift; do not delete')
        app=apps[0];provider=providers[0]
        require(not any(x['provider']==provider['pk'] and x['pk']!=app['pk'] for x in s['apps']),'Shared provider')
        plan={'app':app,'provider':provider,'outpost':outpost,'native_uid':d['metadata']['uid'],'ingress_uid':ingress['metadata']['uid']}
        digest=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if a.apply:
            require(a.approve_plan_hash==digest,'Fresh hash approval required')
            (root/'before.json').write_text(json.dumps(s));(root/'uncertain.json').write_text(json.dumps(plan))
            api.call('PATCH','outposts/instances/'+outpost['pk']+'/',{'providers':[p for p in outpost['providers'] if p!=provider['pk']]})
            api.call('DELETE','core/applications/public-web-grafana/')
            api.call('DELETE','providers/proxy/'+str(provider['pk'])+'/')
            after=m.snapshot(api)
            require(not any(x['slug']=='public-web-grafana' for x in after['apps']),'Gate deletion not confirmed')
            require(not any(x['pk']==provider['pk'] for x in after['providers']),'Provider deletion not confirmed')
            require([x for x in s['apps'] if x['slug']=='grafana']==[x for x in after['apps'] if x['slug']=='grafana'],'Native app changed')
            require(s['groups']==after['groups'],'Group memberships changed')
            require(next(x for x in after['outposts'] if x['pk']==outpost['pk'])['providers']==[p for p in outpost['providers'] if p!=provider['pk']],'Other outpost assignment changed')
            (root/'after.json').write_text(json.dumps(after));(root/'uncertain.json').unlink()
        print(json.dumps({'operations':3,'plan_hash':digest,'applied':a.apply}))
if __name__=='__main__':main()
