#!/usr/bin/env python3
"""Provision narrowly routed Grafana alerts; admin credentials never leave the host."""
import json,shlex,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parents[2]
REMOTE=r'''
import sys,json,subprocess,urllib.request,urllib.error,base64
r=json.load(sys.stdin);k=['kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml','-n','cattle-monitoring-system']
s=json.loads(subprocess.check_output(k+['get','secret','socrat-grafana-admin','-o','json'],stderr=subprocess.DEVNULL))['data']
a=base64.b64decode(s['admin-user']).decode()+':'+base64.b64decode(s['admin-password']).decode()
v=json.loads(subprocess.check_output(k+['get','svc','kube-prometheus-stack-grafana','-o','json'],stderr=subprocess.DEVNULL))['spec']
u='http://'+v['clusterIP']+':'+str(v['ports'][0]['port'])+r['path']
req=urllib.request.Request(u,data=json.dumps(r['body']).encode()if r.get('body')is not None else None,method=r['method'],headers={'Authorization':'Basic '+base64.b64encode(a.encode()).decode(),'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(req,timeout=25)as response:status=response.status;raw=response.read().decode()
except urllib.error.HTTPError as e:status=e.code;raw=e.read().decode()
try:body=json.loads(raw)
except ValueError:body={}
print(json.dumps({'status':status,'body':body}))
'''
def api(method,path,body=None):
    r=subprocess.run(['ssh','socrat-0','python3 -c '+shlex.quote(REMOTE)],input=json.dumps({'method':method,'path':path,'body':body}),text=True,capture_output=True,check=True)
    return json.loads(r.stdout)
def main():
    definition=json.loads((BASE/'docs/n8n/yandex-session-alerts.json').read_text())
    folder=api('GET','/api/folders/automation')
    if folder['status']==404:
        assert api('POST','/api/folders',{'uid':'automation','title':'Automation'})['status']<300
    else:assert folder['status']==200
    cp=definition['contactPoint'];existing=api('GET','/api/v1/provisioning/contact-points');assert existing['status']==200
    method='PUT'if any(c.get('uid')==cp['uid']for c in existing['body'])else'POST'
    path='/api/v1/provisioning/contact-points'+('/'+cp['uid']if method=='PUT'else'')
    result=api(method,path,cp);assert result['status']<300,result['body']
    for rule in definition['rules']:
        current=api('GET','/api/v1/provisioning/alert-rules/'+rule['uid'])
        method='PUT'if current['status']==200 else 'POST'
        assert current['status']in [200,404]
        path='/api/v1/provisioning/alert-rules'+('/'+rule['uid']if method=='PUT'else'')
        result=api(method,path,rule);assert result['status']<300,result['body']
        print('Grafana alert provisioned:',rule['uid'])
if __name__=='__main__':main()
