import importlib.util,json,base64
from pathlib import Path
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--credentials',type=Path,required=True)
parser.add_argument('--artifacts',type=Path,required=True)
args=parser.parse_args()
s=importlib.util.spec_from_file_location('b',Path(__file__).with_name('otel-production-bootstrap.py'));b=importlib.util.module_from_spec(s);s.loader.exec_module(b);ns=b.NS
cert=b.resource('Certificate','otel-tls-grafana',{'secretName':'otel-tls-grafana','commonName':'grafana','duration':'2160h','renewBefore':'720h','issuerRef':{'name':'otel-ca','kind':'Issuer'},'privateKey':{'algorithm':'ECDSA','size':256,'rotationPolicy':'Always'},'usages':['digital signature','client auth']});b.kube('apply','-f','-','-o','json',document=cert);b.kube('-n',ns,'wait','--for=condition=Ready','certificate/otel-tls-grafana','--timeout=90s')
leaf=b.kube('-n',ns,'get','secret','otel-tls-grafana','-o','json')['data'];secure={name:base64.b64decode(leaf[key]).decode() for name,key in [('tlsCACert','ca.crt'),('tlsClientCert','tls.crt'),('tlsClientKey','tls.key')]}
sources=[{'name':name,'uid':name.lower(),'type':name.lower(),'access':'proxy','url':'https://10.250.0.3:'+str(port),'isDefault':False,'editable':False,'jsonData':{'tlsAuth':True,'tlsAuthWithCACert':True,'tlsSkipVerify':False},'secureJsonData':secure}for name,port in [('Loki',3100),('Tempo',3200)]]
sources[0]['jsonData']['derivedFields']=[{'name':'TraceID','matcherRegex':'trace_id=([0-9a-f]{32})','datasourceUid':'tempo','url':'${__value.raw}'}]
sources[1]['jsonData']['tracesToLogsV2']={'datasourceUid':'loki','spanStartTimeShift':'-1m','spanEndTimeShift':'1m','filterByTraceID':True}
secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'otel-grafana-datasources','namespace':ns,'labels':{**b.LABELS,'grafana_datasource':'1'}},'type':'Opaque','data':{'otel-datasources.yaml':base64.b64encode(json.dumps({'apiVersion':1,'datasources':sources}).encode()).decode()}}
b.kube('apply','-f','-','-o','json',document=secret)
role=b.kube('-n',ns,'get','role','otel-host-socrat-0','-o','json');role['rules'][0]['resourceNames'].append('otel-tls-grafana');role['rules'].append({'apiGroups':[''],'resources':['secrets'],'resourceNames':['otel-grafana-datasources'],'verbs':['get','patch']});b.kube('apply','-f','-','-o','json',document=role)
p=(args.credentials/'socrat-0/credentials.json');cfg=json.loads(p.read_text());cfg['grafanaDatasourceSecret']={'leafSecret':'otel-tls-grafana','targetSecret':'otel-grafana-datasources'};p.write_text(json.dumps(cfg));print('Native authenticated Loki/Tempo datasource provisioning requested; prometheus UID untouched')
