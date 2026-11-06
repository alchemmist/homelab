import copy,importlib.util,json
from pathlib import Path
import pytest
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

def test_create_only_preserves_native_admission():
 s=state();before=copy.deepcopy(s);ops,outpost=m.plan(s,services())
 assert s==before and outpost['providers']==[99]
 assert ops[0]['groups']==['reader']
 assert ops[0]['provider']['skip_path_regex']=='^$'
 assert not ops[0]['provider']['intercept_header_auth']
 assert ops[0]['provider']['cookie_domain']=='grafana.socrat.alchemmist.xyz'

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

def test_exact_converged_readback_and_drift_stop():
 s=state();ops,_=m.plan(s,services());s['providers']=[dict(ops[0]['provider'],pk=7)]
 s['apps'].append({'slug':'public-web-grafana','pk':'gate','provider':7,'meta_description':m.OWNER,'policy_engine_mode':'any'})
 s['bindings'].append({'target':'gate','group':'reader','enabled':True,'failure_result':False});s['outposts'][0]['providers'].append(7)
 assert m.plan(s,services())[0]==[]
 s['providers'][0]['skip_path_regex']='^/'
 with pytest.raises(ValueError):m.plan(s,services())

def test_catalog_proxy_and_native_routes_are_explicit():
 import yaml,subprocess
 catalog=json.loads((ROOT/'deploy/public-web/services.json').read_text())
 rendered=list(yaml.safe_load_all(subprocess.check_output(['helm','template','test',str(ROOT/'charts/public-web-entry')],text=True)))
 ingresses=[d for d in rendered if d and d['kind']=='Ingress']
 assert len(ingresses)==6
 for slug,entry in catalog.items():
  i=next(d for d in ingresses if d['spec']['rules'][0]['host']==entry['host'])
  assert i['metadata']['namespace']=='identity'
  assert i['spec']['rules'][0]['http']['paths'][0]['backend']['service']['name']=='authentik-server'
 mcp=next(d for d in ingresses if d['metadata']['name']=='public-web-grafana-mcp')
 assert mcp['spec']['rules'][0]['http']['paths'][0]['path']=='/mcp'
 assert all(d['spec']['tls'] for d in ingresses)
