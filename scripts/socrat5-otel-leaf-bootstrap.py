#!/usr/bin/env python3
"""One-time additive leaf/RBAC only for socrat-5. Never touch existing CA/leaves."""
import subprocess,json,pathlib,os
NS='cattle-monitoring-system';NODE='socrat-5';SA='otel-host-'+NODE;LEAF='otel-tls-'+NODE

def k(*args,document=None):
 p=subprocess.run(['k3s','kubectl',*args],input=json.dumps(document) if document else None,text=True,capture_output=True,timeout=180)
 if p.returncode:raise RuntimeError('Kubernetes leaf operation failed; private evidence, no blind replay')
 return p.stdout

def main():
 os.umask(0o077);root=pathlib.Path('/var/lib/homelab-recovery/20261110-socrat5-otel-leaf');root.mkdir(mode=0o700,exist_ok=False)
 for kind,name in [('certificate',LEAF),('serviceaccount',SA),('role',SA),('rolebinding',SA)]:
  assert not k('-n',NS,'get',kind,name,'--ignore-not-found','-o','name').strip(),'STOP unexpected existing identity'
 meta=lambda name:{'name':name,'namespace':NS,'labels':{'app.kubernetes.io/part-of':'homelab-otel'}}
 docs=[{'apiVersion':'cert-manager.io/v1','kind':'Certificate','metadata':meta(LEAF),'spec':{'secretName':LEAF,'commonName':'otel-'+NODE,'duration':'2160h','renewBefore':'720h','issuerRef':{'name':'otel-ca','kind':'Issuer'},'privateKey':{'algorithm':'ECDSA','size':256,'rotationPolicy':'Always'},'usages':['digital signature','server auth','client auth'],'ipAddresses':['10.250.0.41']}},
 {'apiVersion':'v1','kind':'ServiceAccount','metadata':meta(SA)},
 {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role','metadata':meta(SA),'rules':[{'apiGroups':[''],'resources':['secrets'],'resourceNames':[LEAF],'verbs':['get']},{'apiGroups':[''],'resources':['serviceaccounts/token'],'resourceNames':[SA],'verbs':['create']}]},
 {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':meta(SA),'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':SA},'subjects':[{'kind':'ServiceAccount','name':SA,'namespace':NS}]}]
 (root/'objects.json').write_text(json.dumps(docs));k('create','-f','-',document={'apiVersion':'v1','kind':'List','items':docs})
 k('-n',NS,'wait','--for=condition=Ready','certificate/'+LEAF,'--timeout=120s')
 creds=root/NODE;creds.mkdir(mode=0o700)
 token=json.loads(k('-n',NS,'create','token',SA,'--duration=24h','-o','json'))['status'];(creds/'token.json').write_text(json.dumps(token))
 ca=json.loads(k('-n',NS,'get','configmap','kube-root-ca.crt','-o','json'))['data']['ca.crt'];(creds/'kubernetes-ca.crt').write_text(ca)
 (creds/'credentials.json').write_text(json.dumps({'namespace':NS,'node':NODE,'serviceAccount':SA,'apiServer':'https://10.250.0.1:6443','secret':LEAF,'sourceReferences':[]}))
 (root/'accepted.json').write_text(json.dumps({'leaf_ready':True,'existing_ca_and_leaves_untouched':True,'new_sa_scope':'own leaf get and own token create only'}));print((root/'accepted.json').read_text())
if __name__=='__main__':main()
