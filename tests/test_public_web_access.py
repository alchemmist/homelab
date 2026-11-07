import copy,importlib.util,json
from pathlib import Path
import pytest
from public_entry_contract import CHARTS, render, values as entry_values
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_web_access',ROOT/'scripts/public-web-access.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def state():
 return {'flows':[{'slug':'default-authentication-flow','pk':'auth'},{'slug':'default-provider-authorization-implicit-consent','pk':'grant'},{'slug':'default-provider-invalidation-flow','pk':'logout'}],
 'flowbindings':[{'target':'auth','stage':'mfa'}],'mfa':[{'pk':'mfa','not_configured_action':'configure'}],
 'apps':[{'slug':'grafana','pk':'native','policy_engine_mode':'any'}],
 'providers':[], 'groups':[{'pk':'reader','name':'app-grafana-viewer','is_superuser':False,'parents':[],'roles':[]}],
 'bindings':[{'target':'native','group':'reader','enabled':True,'failure_result':False}],
 'outposts':[{'pk':'embedded','managed':'goauthentik.io/outposts/embedded','providers':[99]}]}

def services():return {'grafana':{'host':'grafana.socrat.alchemmist.xyz','upstream':'http://grafana.monitoring.svc.cluster.local:80','admissionFrom':'grafana'}}

def test_legacy_proxy_creation_is_retired_without_mutation():
 s=state();before=copy.deepcopy(s)
 with pytest.raises(ValueError,match='retired'):m.plan(s,services())
 assert s==before
 assert m.plan(s,{})[0]==[]

@pytest.mark.parametrize('change',[lambda s:s['mfa'][0].update(not_configured_action='skip'),lambda s:s['groups'][0].update(parents=['owner']),lambda s:s['bindings'][0].update(negate=True),lambda s:s['bindings'][0].update(user='someone'),lambda s:s['apps'][0].update(policy_engine_mode='all')])
def test_reject_unsafe_baseline(change):
 s=state();change(s)
 with pytest.raises(ValueError):m.plan(s,services())

def test_no_arbitrary_bypass_or_upstream():
 for key,value in [('machinePathRegex','^/'),('upstream','https://example.org'),('host','grafana.example.org')]:
  v=services();v['grafana'][key]=value
  with pytest.raises(ValueError):m.plan(state(),v)

def test_no_foreign_provider_adoption():
 s=state();s['providers']=[{'name':'public-web-grafana','pk':7}]
 with pytest.raises(ValueError):m.plan(s,services())

def test_catalog_is_empty_and_routes_use_native_or_explicit_public_access():
 catalog=json.loads((ROOT/'deploy/public-web/services.json').read_text())
 assert catalog=={}
 ingresses=[d for d in render() if d and d['kind']=='Ingress']
 assert len(ingresses)==9
 assert all(d['spec']['tls'] for d in ingresses)
 assert all(p['backend']['service']['name']!='authentik-server' for d in ingresses for rule in d['spec']['rules'] for p in rule['http']['paths'])
 for owner in ('open-webui','litellm','searxng','syncthing','uptime-kuma'):
  for d in render(owner):
   if d['kind']=='Ingress':assert not d['metadata']['name'].startswith('public-web-')

def test_public_probe_reuses_migration_owned_addresses():
 spec=importlib.util.spec_from_file_location('public_entry_check',ROOT/'scripts/check-public-web-entry.py')
 c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
 assert len(c.addresses())==2
 assert c.addresses(['109.173.40.247','109.120.141.97'])==['109.173.40.247','109.120.141.97']
 with pytest.raises(ValueError):c.addresses(['10.250.0.1','109.120.141.97'])
 with pytest.raises(ValueError):c.addresses(['109.120.141.97','109.120.141.97'])

@pytest.mark.parametrize('owner,key,value',[('rancher','service','unprotected-backend'),('rancher','namespace','identity'),('grafana-mcp','port',8080),('grafana-mcp','path','/'),('grafana','service','grafana')])
def test_chart_rejects_mislabeled_authorization(owner,key,value,tmp_path):
 import yaml,subprocess
 values=copy.deepcopy(entry_values(owner))
 values['routes'][0][key]=value
 overrides=values if CHARTS[owner].startswith('deploy/') else {'publicEntry':values}
 p=tmp_path/'values.yaml';p.write_text(yaml.safe_dump(overrides))
 result=subprocess.run(['helm','template',owner,str(ROOT/CHARTS[owner]),'-f',str(p)],text=True,capture_output=True)
 assert result.returncode!=0

def test_rancher_public_proxy_denies_local_password_without_changing_private_backend():
 import yaml,subprocess
 docs=render('rancher')
 config=next(x['data']['nginx.conf'] for x in docs if x['kind']=='ConfigMap' and x['metadata']['name']=='public-web-rancher-policy')
 assert '~^(POST|PUT|PATCH|DELETE):/v3-public/localProviders(?:/|$) 1;' in config
 assert 'if ($deny_local_password) { return 403; }' in config
 assert 'http://rancher.cattle-system.svc.cluster.local:80' in config
 assert 'proxy_set_header Upgrade $http_upgrade' in config
 assert 'proxy_set_header X-HTTP-Method-Override ""' in config
 d=next(x for x in docs if x['kind']=='Deployment' and x['metadata']['name']=='public-web-rancher-proxy')
 pod=d['spec']['template']['spec'];c=pod['containers'][0]
 assert pod['automountServiceAccountToken'] is False and pod['securityContext']['runAsNonRoot']
 assert c['securityContext']['readOnlyRootFilesystem'] and c['securityContext']['capabilities']['drop']==['ALL']
 assert '@sha256:' in c['image']
 i=next(x for x in docs if x['kind']=='Ingress' and x['metadata']['name']=='public-web-rancher')
 assert i['spec']['rules'][0]['http']['paths'][0]['backend']['service']['name']=='public-web-rancher-proxy'
