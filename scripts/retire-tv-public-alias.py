#!/usr/bin/env python3
"""Delete only the three exact resources created for the retired TV alias; never prune."""
import argparse,fcntl,hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path('/var/lib/homelab-tv-alias-retirement')
OWNED=[('ingress','public-web-grafana-tv','b1934513-0887-4bdc-b3d1-4468047cc002','/apis/networking.k8s.io/v1/namespaces/identity/ingresses/'),('certificate','public-web-grafana-tv-tls','40174498-dae6-488f-b131-117092f625eb','/apis/cert-manager.io/v1/namespaces/identity/certificates/'),('secret','public-web-grafana-tv-tls','49ba877b-f7af-4891-a842-095cc05b9cda','/api/v1/namespaces/identity/secrets/')]
def need(ok,msg):
    if not ok:raise RuntimeError(msg)
def get(kind,name):
    r=subprocess.run(['kubectl','-n','identity','get',kind,name,'--ignore-not-found','-o','json'],capture_output=True,check=True)
    return json.loads(r.stdout) if r.stdout.strip() else None
def inspect():
    out=[]
    for kind,name,uid,path in OWNED:
        o=get(kind,name)
        if o:
            need(o['metadata']['uid']==uid,'Unowned replacement; stop')
            if kind=='ingress':need(o['spec']['rules'][0]['host']=='tv.alchemmist.xyz' and o['metadata']['annotations'].get('argocd.argoproj.io/tracking-id')=='public-web-entry:networking.k8s.io/Ingress:identity/public-web-grafana-tv','Ingress ownership drift')
            if kind=='certificate':need(o['spec']['dnsNames']==['tv.alchemmist.xyz'],'Certificate scope drift')
            if kind=='secret':need(o['metadata']['annotations'].get('cert-manager.io/alt-names')=='tv.alchemmist.xyz','Secret scope drift')
            out.append(o)
    return out
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    need(not ROOT.is_symlink(),'Unsafe state');ROOT.mkdir(mode=0o700,exist_ok=True);need(ROOT.stat().st_uid==0 and not ROOT.stat().st_mode&0o077,'Unsafe state')
    with (ROOT/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);need(not (ROOT/'uncertain.json').exists(),'Uncertain deletion; inspect privately')
        objects=inspect();h=hashlib.sha256(json.dumps(objects,sort_keys=True).encode()).hexdigest()
        if a.apply and objects:
            need(a.approve_plan_hash==h,'Fresh exact approval required');need(not (ROOT/'before.json').exists(),'Existing cleanup backup; inspect')
            (ROOT/'before.json').write_text(json.dumps(objects));(ROOT/'uncertain.json').write_text(json.dumps({'plan_hash':h}))
            for kind,name,uid,path in OWNED:
                o=get(kind,name)
                if not o:continue
                need(o['metadata']['uid']==uid,'Concurrent replacement; stop')
                options={'apiVersion':'v1','kind':'DeleteOptions','propagationPolicy':'Foreground','preconditions':{'uid':uid,'resourceVersion':o['metadata']['resourceVersion']}}
                r=subprocess.run(['kubectl','delete','--raw',path+name,'-f','-'],input=json.dumps(options).encode(),capture_output=True)
                need(r.returncode==0 or b'NotFound' in r.stderr,'Scoped delete failed; inspect privately')
            remaining=inspect();need(not any(o['kind']=='Secret' for o in remaining),'Secret deletion not confirmed')
            (ROOT/'after.json').write_text(json.dumps({'plan_hash':h,'delete_requests_completed':True}));(ROOT/'uncertain.json').unlink()
        print(json.dumps({'operations':len(objects),'plan_hash':h,'applied':bool(a.apply and objects)}))
if __name__=='__main__':main()
