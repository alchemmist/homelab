"""Stable runtime Secret; no credentials in Helm values or output."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

root=Path(sys.argv[1]);path=root/'credentials.json'
kube=['kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml','-n','identity']
if not path.exists():
    check=subprocess.run(kube+['get','secret','authentik-runtime','--ignore-not-found','-o','name'],capture_output=True,text=True,check=True)
    if check.stdout.strip():raise SystemExit('Runtime Secret exists but credential file is missing; refusing implicit rotation')
    claims=subprocess.run(kube+['get','pvc','-o','name'],capture_output=True,text=True,check=True)
    if claims.stdout.strip():raise SystemExit('Identity PVCs already exist without credential file; restore credentials before deployment')
    values={'AUTHENTIK_SECRET_KEY':secrets.token_urlsafe(64),
            'AUTHENTIK_POSTGRESQL__HOST':'authentik-postgres',
            'AUTHENTIK_POSTGRESQL__NAME':'authentik',
            'AUTHENTIK_POSTGRESQL__USER':'authentik',
            'AUTHENTIK_POSTGRESQL__PASSWORD':secrets.token_urlsafe(48),
            'AUTHENTIK_BOOTSTRAP_PASSWORD':secrets.token_urlsafe(32),
            'AUTHENTIK_BOOTSTRAP_TOKEN':secrets.token_urlsafe(48),
            'AUTHENTIK_ERROR_REPORTING__ENABLED':'false',
            'AUTHENTIK_ERROR_REPORTING__SEND_PII':'false',
            'AUTHENTIK_DISABLE_UPDATE_CHECK':'true'}
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(values,f)
values=json.loads(path.read_text());path.chmod(0o600)
# Existing API consumers retain the historical key as a compatibility alias.
# Never inject that administrative machine token or old bootstrap password into pods.
runtime_values=dict(values)
automation_path=root/'automation-api.json'
if automation_path.exists():
    automation=json.loads(automation_path.read_text())
    if automation.get('status')!='active' or automation.get('token')!=values['AUTHENTIK_BOOTSTRAP_TOKEN']:
        raise SystemExit('Incomplete automation migration; refusing runtime credential update')
    for key in ['AUTHENTIK_BOOTSTRAP_TOKEN','AUTHENTIK_BOOTSTRAP_PASSWORD']:
        runtime_values.pop(key,None)
manifest={'apiVersion':'v1','kind':'Secret','metadata':{'name':'authentik-runtime','namespace':'identity'},'type':'Opaque','stringData':runtime_values}
subprocess.run(kube+['apply','-f','-'],input=json.dumps(manifest),text=True,stdout=subprocess.DEVNULL,check=True)
print('Stable runtime credentials installed without displaying secrets')
