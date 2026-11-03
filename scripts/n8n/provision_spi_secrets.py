#!/usr/bin/env python3
"""Bootstrap private SPI secrets and a dedicated model key. No secret is printed.

Run locally. Remote bootstrap keeps existing values and never copies the App key.
Native n8n credentials are created once; references live in a private local mapping.
"""
import json
import shlex
import sys
import subprocess
from pathlib import Path
from sync import api, CONFIG
REMOTE=r'''
import base64,json,secrets,subprocess,urllib.request
k=['kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml']
def get(ns,name,optional=False):
 r=subprocess.run(k+['-n',ns,'get','secret',name,'-o','json'],capture_output=True,text=True)
 if r.returncode:
  if optional and '(NotFound)' in r.stderr:return None
  raise RuntimeError('SECRET_ACCESS_FAILED')
 return {a:base64.b64decode(b).decode()for a,b in json.loads(r.stdout)['data'].items()}
def put(ns,name,data):
 obj={'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':ns},'type':'Opaque','stringData':data}
 subprocess.run(k+['apply','-f','-'],input=json.dumps(obj),capture_output=True,text=True,check=True)
ingress=get('cattle-monitoring-system','spi-alert-ingress',True)
if ingress is None:
 ingress={'token':secrets.token_urlsafe(40)};put('cattle-monitoring-system','spi-alert-ingress',ingress)
worker=get('automation','spi-triage',True)
if worker is None:
 master=get('llm','litellm-env')['LITELLM_MASTER_KEY']
 svc=json.loads(subprocess.check_output(k+['-n','llm','get','svc','litellm','-o','json'],stderr=subprocess.DEVNULL))['spec']
 url='http://'+svc['clusterIP']+':'+str(svc['ports'][0]['port'])+'/key/generate'
 body={'key_alias':'socrat-spi-triage','models':['qwen3.8-27b'],'rpm_limit':3,'tpm_limit':30000,'max_parallel_requests':1,'metadata':{'purpose':'read-only incident triage'}}
 with urllib.request.urlopen(urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+master,'Content-Type':'application/json'}),timeout=30)as r:key=json.load(r)['key']
 worker={'WORKER_TOKEN':secrets.token_urlsafe(40),'LITELLM_KEY':key,'GRAFANA_TOKEN':get('cattle-monitoring-system','grafana-mcp-credentials')['grafana-token']}
 put('automation','spi-triage',worker)
if get('automation','spi-github-installation',True)is None:put('automation','spi-github-installation',{'token':''})
print(json.dumps({'worker':worker['WORKER_TOKEN'],'ingress':ingress['token']}))
'''
def main():
    r=subprocess.run(['ssh','socrat-0','python3 -c '+shlex.quote(REMOTE)],text=True,capture_output=True,check=True)
    secret=json.loads(r.stdout)
    if '--secrets-only' in sys.argv:
        print('SPI runtime secrets provisioned; native credentials deferred until extension rollout.');return
    api('GET','credentials/schema/socratAlertIngress')
    path=CONFIG/'spi-credentials.json'
    mapping=json.loads(path.read_text()) if path.exists() else {}
    for alias,kind,name,data in [
        ('worker','httpHeaderAuth','SPI worker internal',{'name':'X-Worker-Token','value':secret['worker']}),
        ('ingress','socratAlertIngress','Socrat alert ingress',{'token':secret['ingress']})]:
        if alias in mapping:continue
        c=api('POST','credentials',{'name':name,'type':kind,'data':data})
        mapping[alias]={'id':c['id'],'name':c['name']}
        CONFIG.mkdir(mode=0o700,parents=True,exist_ok=True)
        import os
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w')as f:json.dump(mapping,f)
    print('SPI secrets and scoped LiteLLM key provisioned; native credentials saved privately.')
if __name__=='__main__':main()
