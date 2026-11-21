#!/usr/bin/env python3
"""Provision the private pilot and bind credentials; does not activate n8n."""
import base64,json,secrets,subprocess
from pathlib import Path
from sync import api,CONFIG
root=Path(__file__).resolve().parents[2]; lms=root.parent/'lms'; docs=root/'docs/n8n/lms-certify'; ns='automation'
wid='UUj3hoNCdbWGY4m7'
if api('GET','workflows/'+wid)['active']:
 raise SystemExit('Refusing to modify dependencies of an active workflow')
def k(args, body: str | None = None) -> str:
 p=subprocess.run(['ssh','-o','BatchMode=yes','socrat-0','kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n automation '+args],input=body,text=True,capture_output=True);p.check_returncode();return p.stdout

def put(kind,name,**body) -> None:
 v={'Deployment':'apps/v1','NetworkPolicy':'networking.k8s.io/v1'}.get(kind,'v1'); version={'apiVersion':v,'kind':kind,'metadata':{'name':name,'namespace':ns},**body}; k('apply -f -',json.dumps(version))
runner='lms-certification-runner'; db='lms-certification-db'; secret='lms-certification-pilot'
if k('get secret certification-pg-common --ignore-not-found -o name').strip():
 raise SystemExit('Certification uses pg-common: refusing to reprovision the legacy pilot database or replace its workflow')
prior=k(f'get secret {secret} --ignore-not-found -o json'); keys={x:base64.b64decode(y).decode() for x,y in json.loads(prior)['data'].items()} if prior.strip() else {i:secrets.token_urlsafe(32) for i in ('RUNNER','JUDGE','POSTGRES_PASSWORD')}
if not prior.strip(): put('Secret',secret,stringData=keys)
def env(name,key) -> dict[str,object]:
 return dict(name=name,valueFrom={'secretKeyRef':{'name':secret,'key':key}})
def deploy(name,container,volumes,**pod) -> None:
 labels={'app':name}; put('Deployment',name,spec={'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':labels},'template':{'metadata':{'labels':labels},'spec':{'automountServiceAccountToken':False,'containers':[container],'volumes':volumes,**pod}}})
def access(name,port) -> None:
 put('Service',name,spec={'selector':{'app':name},'ports':[{'port':port,'targetPort':port}]});put('NetworkPolicy',name,spec={'podSelector':{'matchLabels':{'app':name}},'policyTypes':['Ingress'],'ingress':[{'from':[{'podSelector':{'matchLabels':{'app':'n8n'}}}],'ports':[{'protocol':'TCP','port':port}]}]})
put('PersistentVolumeClaim',db,spec={'storageClassName':'local-path','accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'1Gi'}}})
put('ConfigMap',db,data={'01-pilot.sql':(docs/'pilot-state.sql').read_text(), '02-audit.sql':(docs/'queue-audit.sql').read_text()})
access(db,5432)
deploy(db,{'name':'postgres','image':'postgres:16-alpine','env':[{'name':'POSTGRES_USER','value':'certification'},{'name':'POSTGRES_DB','value':'certification'},env('POSTGRES_PASSWORD','POSTGRES_PASSWORD')],'volumeMounts':[{'name':'data','mountPath':'/var/lib/postgresql/data'},{'name':'sql','mountPath':'/docker-entrypoint-initdb.d'}],'readinessProbe':{'tcpSocket':{'port':5432}}},[{'name':'data','persistentVolumeClaim':{'claimName':db}},{'name':'sql','configMap':{'name':db}}])
files={p.name:p.read_text() for p in (lms/'runner').glob('*.py')};files['requirements.txt']=(lms/'runner/requirements.txt').read_text(); files['launch.py']='import uvicorn\nfrom runner.app import create_app\nfrom runner.engine import DockerEngine\napp=create_app(catalog={},engine=DockerEngine("lms-certification-sandbox:pilot",owner="certification-pilot"))\nuvicorn.run(app,host="0.0.0.0",port=9000,access_log=False)\n'; put('ConfigMap',runner,data=files)
access(runner,9000)
deploy(runner,{'name':'runner','image':'python:3.12-slim','command':['sh','-ec','python -m venv /tmp/venv && /tmp/venv/bin/pip -q install --no-cache-dir -r /app/runner/requirements.txt && cd /app && exec /tmp/venv/bin/python -m runner.launch'],'env':[env('LMS_RUNNER_KEY','JUDGE'),env('LMS_CERTIFICATION_RUNNER_KEY','RUNNER'),{'name':'PYTHONDONTWRITEBYTECODE','value':'1'},{'name':'HOME','value':'/tmp'}],'securityContext':{'runAsUser':1000,'runAsGroup':1000,'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},'volumeMounts':[{'name':'code','mountPath':'/app/runner','readOnly':True},{'name':'docker','mountPath':'/var/run/docker.sock','readOnly':True}], 'readinessProbe':{'httpGet':{'path':'/healthz','port':9000}}},[{'name':'code','configMap':{'name':runner}},{'name':'docker','hostPath':{'path':'/run/user/1000/docker.sock','type':'Socket'}}],nodeSelector={'kubernetes.io/hostname':'socrat-1'})
for name in (db,runner):
 print(k(f'rollout status deployment/{name} --timeout=65s').strip(),flush=True)
wid='UUj3hoNCdbWGY4m7'; w=api('GET','workflows/'+wid)
if w['active']:raise SystemExit('refusing to update active workflow')
lite=base64.b64decode(k("get secret lms-certify -o jsonpath='{.data.LITELLM_KEY}'")).decode()
roles={'CERTIFICATION_DB':('postgres',dict(host=db+'.automation.svc.cluster.local',port=5432,database='certification',user='certification',password=keys['POSTGRES_PASSWORD'],ssl='disable',sshTunnel=False)), 'SANDBOX':('httpHeaderAuth',dict(name='X-Certification-Key',value=keys['RUNNER'])),'LITELLM':('httpHeaderAuth',dict(name='Authorization',value='Bearer '+lite))}
path=CONFIG/'lms-certification-pilot-credential-ids.json'; mapping=json.loads(path.read_text()) if path.exists() else {}
for role,(typ,data) in roles.items():
 if role not in mapping:
  v=api('POST','credentials',{'name':'LMS certification '+role,'type':typ,'data':data}); mapping[role]={'id':v['id'],'name':v['name']}; path.touch(mode=0o600,exist_ok=True); path.write_text(json.dumps(mapping))
body=json.loads((docs/'workflow.json').read_text())
for n in body['nodes']:
 for typ,c in n.get('credentials',{}).items(): n['credentials'][typ]=mapping[c['name']]
 if 'url' in n['parameters']: n['parameters']['url']=n['parameters']['url'].replace('REPLACE_RUNNER',runner+'.automation.svc.cluster.local')
api('PUT','workflows/'+wid,body)
print('Pilot credentials bound; inactive pending sandbox smoke')
