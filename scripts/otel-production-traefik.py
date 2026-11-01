import importlib.util,json,base64
from pathlib import Path
import yaml
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--credentials',type=Path,required=True)
parser.add_argument('--artifacts',type=Path,required=True)
args=parser.parse_args()
s=importlib.util.spec_from_file_location('b',Path(__file__).with_name('otel-production-bootstrap.py'));b=importlib.util.module_from_spec(s);s.loader.exec_module(b);ns=b.NS
cert=b.resource('Certificate','otel-tls-traefik',{'secretName':'otel-tls-traefik','commonName':'traefik','duration':'2160h','renewBefore':'720h','issuerRef':{'name':'otel-ca','kind':'Issuer'},'privateKey':{'algorithm':'ECDSA','size':256,'rotationPolicy':'Always'},'usages':['digital signature','client auth']})
b.kube('apply','-f','-','-o','json',document=cert);b.kube('-n',ns,'wait','--for=condition=Ready','certificate/otel-tls-traefik','--timeout=90s')
leaf=b.kube('-n',ns,'get','secret','otel-tls-traefik','-o','json')['data'];mirror={'apiVersion':'v1','kind':'Secret','metadata':{'name':'otel-traefik-tls','namespace':'kube-system','labels':b.LABELS},'type':'Opaque','data':leaf};b.kube('apply','-f','-','-o','json',document=mirror)
role=b.kube('-n',ns,'get','role','otel-host-socrat-0','-o','json');role['rules'][0]['resourceNames'].append('otel-tls-traefik');b.kube('apply','-f','-','-o','json',document=role)
for obj in [ {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role','metadata':{'name':'otel-traefik-secret-writer','namespace':'kube-system','labels':b.LABELS},'rules':[{'apiGroups':[''],'resources':['secrets'],'resourceNames':['otel-traefik-tls'],'verbs':['get','patch']}]}, {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':{'name':'otel-traefik-secret-writer','namespace':'kube-system','labels':b.LABELS},'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':'otel-traefik-secret-writer'},'subjects':[{'kind':'ServiceAccount','name':'otel-host-socrat-0','namespace':ns}]} ]:b.kube('apply','-f','-','-o','json',document=obj)
cfg=(args.credentials/'socrat-0/credentials.json');data=json.loads(cfg.read_text());data['mirroredTLSSecrets']=[{'namespace':ns,'secret':'otel-tls-traefik','targetNamespace':'kube-system','targetSecret':'otel-traefik-tls'}];cfg.write_text(json.dumps(data))
chart=b.kube('-n','kube-system','get','helmchartconfig','traefik','-o','json');values=yaml.safe_load(chart['spec']['valuesContent']) or {};additional=values.get('additionalArguments',[]);additional=[x for x in additional if not x.startswith('--tracing.')];additional.extend(['--tracing.serviceName=traefik','--tracing.sampleRate=1.0','--tracing.otlp.grpc.endpoint=10.250.0.1:44317','--tracing.otlp.grpc.tls.ca=/etc/otel-traces/ca.crt','--tracing.otlp.grpc.tls.cert=/etc/otel-traces/tls.crt','--tracing.otlp.grpc.tls.key=/etc/otel-traces/tls.key']);values['additionalArguments']=additional
volumes=values.get('volumes',[]);volumes=[v for v in volumes if v.get('name')!='otel-traefik-tls'];volumes.append({'name':'otel-traefik-tls','mountPath':'/etc/otel-traces','type':'secret'});values['volumes']=volumes
chart['spec']['valuesContent']=yaml.safe_dump(values,sort_keys=False);b.kube('apply','-f','-','-o','json',document=chart);(args.artifacts/'traefik-values.yaml').write_text(chart['spec']['valuesContent']);print('Requested stock Traefik tracing with AlwaysOn source sampling and native mTLS OTLP')
