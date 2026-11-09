"""Native app routes and explicit private/public exception boundaries."""
from pathlib import Path
import json
import subprocess
import yaml
import pytest
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('chart,ns,service,authorization',[
 ('open-webui','llm','open-webui','native-oidc'),
 ('searxng','llm','searxng','public'),
 ('uptime-kuma','uptime-kuma','uptime-kuma','native-login'),
 ('syncthing','syncthing','public-web-syncthing-0','native-login'),
])
def test_direct_route_and_reject_mislabeled_backend(chart,ns,service,authorization,tmp_path):
 values=yaml.safe_load((ROOT/f'charts/{chart}/values.yaml').read_text())
 route=values['publicEntry']['routes'][0]
 assert route['namespace']==ns and route['service']==service and route['authorization']==authorization
 route['service']='unreviewed-service'
 override=tmp_path/'override.yaml';override.write_text(yaml.safe_dump(values))
 p=subprocess.run(['helm','template',chart,str(ROOT/f'charts/{chart}'),'-f',str(override)],capture_output=True,text=True)
 assert p.returncode!=0


def test_private_reader_has_only_pinned_idp_egress_and_storage_keeps_s3_iam():
 text=subprocess.check_output(['helm','template','rustfs',str(ROOT/'charts/rustfs'),'-n','rustfs','-f',str(ROOT/'charts/rustfs/values-foundation-live.yaml')],text=True)
 docs=[d for d in yaml.safe_load_all(text) if d]
 reader=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='rustfs-gateway')
 env=reader['spec']['template']['spec']['containers'][0]['env']
 # Concurrent main explicitly made RustFS private; do not restore anonymous evidence.
 values=yaml.safe_load((ROOT/'charts/rustfs/values-foundation-live.yaml').read_text())
 assert values['browserRoutes']['unifiedOrigin'] is True
 assert {e['name'] for e in env}=={'AUTH_URL','S3_ACCESS_KEY','S3_SECRET_KEY'}
 assert next(e['value'] for e in env if e['name']=='AUTH_URL')=='https://rustfs.socrat.alchemmist.xyz/outpost.goauthentik.io/auth/nginx'
 policy=next(d for d in docs if d['kind']=='NetworkPolicy' and d['metadata']['name']=='rustfs-gateway-isolation')
 assert len(policy['spec']['egress'])==2+len(values['authEgressCIDRs'])+(2 if values.get('authViaTraefik') else 0)
 tls=[r for r in policy['spec']['egress'] if any(p['port']==443 for p in r['ports'])]
 assert {t['ipBlock']['cidr'] for r in tls for t in r['to'] if 'ipBlock' in t}==set(values['authEgressCIDRs'])
 assert '0.0.0.0/0' not in json.dumps(tls)
 storage=next(d for d in docs if d['kind']=='NetworkPolicy' and d['metadata']['name']=='rustfs-isolation')
 assert 'authentik' not in json.dumps(storage['spec']['ingress'])
 proxy=next(d for d in docs if d['kind']=='ConfigMap' and d['metadata']['name']=='rustfs-console-http')
 assert 'auth_request' not in proxy['data']['nginx.conf']
 assert 'Cookie' not in proxy['data']['nginx.conf']
 assert all(p['path'].startswith('/outpost.goauthentik.io/') and rule['host']=='rustfs.socrat.alchemmist.xyz' for d in docs if d['kind']=='Ingress' for rule in d['spec']['rules'] for p in rule['http']['paths'] if p['backend']['service']['name']=='authentik-server')


def test_syncthing_public_route_has_no_extra_basic_auth_wrapper():
 nginx=(ROOT/'charts/syncthing/files/syncthing-policy.conf').read_text()
 assert 'auth_basic' not in nginx and 'auth_request' not in nginx
 assert 'return 410' in nginx
 assert 'proxy_pass http://gui0' in nginx


def test_obsolete_xui_controller_source_is_removed():
 assert not (ROOT/'deploy/argocd/apps/xui-auth-gateway.yaml').exists()
 assert not (ROOT/'deploy/xui-auth-gateway').exists()
