import importlib.util,json,subprocess,copy
from pathlib import Path
import pytest,yaml
ROOT=Path(__file__).resolve().parents[1]
def module(name):
 s=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_scoped_web_groups_create_no_users():
 m=module('public-web-role-groups');ops=m.plan([])
 assert {x['name'] for x in ops}=={'syncthing-web-admins','uptime-kuma-web-admins'}
 assert all(x['users']==x['parents']==x['children']==x['roles']==[] and x['is_superuser'] is False for x in ops)
 assert m.plan(ops)==[]
@pytest.mark.parametrize('field,value',[('is_superuser',True),('parents',['owner']),('roles',['admin']),('attributes',{}),('children',['inheritor'])])
def test_reject_foreign_or_privileged_web_group(field,value):
 m=module('public-web-role-groups');ops=m.plan([]);ops[0][field]=value
 with pytest.raises(RuntimeError):m.plan(ops)

def grafana():
 e={'GF_AUTH_GENERIC_OAUTH_ENABLED':'true','GF_AUTH_GENERIC_OAUTH_CLIENT_ID':'socrat-grafana','GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT':'true','GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP':'false','GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN':'false','GF_AUTH_GENERIC_OAUTH_ALLOWED_GROUPS':'homelab-owner homelab-observer homelab-platform-operator homelab-project-maintainer','GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH':"contains(groups[*], 'homelab-owner') && 'GrafanaAdmin' || 'Viewer'",'GOMEMLIMIT':'1GiB'}
 env=[{'name':k,'value':v} for k,v in e.items()]+[{'name':'GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET','valueFrom':{'secretKeyRef':{'name':'socrat-authentik-grafana','key':'client-secret'}}}]
 return {'spec':{'template':{'spec':{'containers':[{'name':'sidecar'},{'name':'grafana','env':env}]}}}}

def test_grafana_only_reviewed_env_changes():
 m=module('grafana-public-sso');d=grafana();before=copy.deepcopy(d);index,changes,result=m.env_plan(d)
 assert d==before and index==1 and set(changes)==set(m.DESIRED)
 assert next(x for x in result if x['name']=='GOMEMLIMIT')['value']=='1GiB'
 for e in before['spec']['template']['spec']['containers'][1]['env']:
  if e['name'] not in m.DESIRED:assert e in result
 d['spec']['template']['spec']['containers'][1]['env']=result
 assert m.env_plan(d)[1]==[]
@pytest.mark.parametrize('key,value',[('GF_AUTH_GENERIC_OAUTH_ENABLED','false'),('GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT','false'),('GF_AUTH_GENERIC_OAUTH_ALLOWED_GROUPS','All'),('GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH',"'GrafanaAdmin'"),('GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP','true')])
def test_grafana_drift_stops(key,value):
 m=module('grafana-public-sso');d=grafana();next(e for e in d['spec']['template']['spec']['containers'][1]['env'] if e['name']==key)['value']=value
 with pytest.raises(RuntimeError):m.env_plan(d)

def test_public_policies_keep_machine_auth_and_block_human_fallbacks():
 gf=(ROOT/'deploy/platform/kube-prometheus-stack/public-entry/files/grafana-policy.conf').read_text()
 assert '~*^Basic 1' in gf and '~^POST:/login/?$ 1' in gf
 assert 'proxy_set_header Authorization ""' not in gf and 'proxy_set_header Upgrade $http_upgrade' in gf
 kuma=(ROOT/'charts/uptime-kuma/files/kuma-policy.conf').read_text()
 assert 'location ^~ /socket.io { return 404; }' in kuma
 assert 'location ^~ /api/push/ { proxy_pass http://kuma; }' in kuma
 assert 'limit_except GET HEAD { deny all; }' in kuma
 assert 'https://kuma.socrat.alchemmist.xyz$request_uri' in kuma
 sync=(ROOT/'charts/syncthing/files/syncthing-policy.conf').read_text()
 assert 'proxy_pass http://gui0/;' in sync and 'auth_basic_user_file /etc/nginx/basic/users' in sync
 assert 'return 410' in sync and 'syncthing-sync-1' not in sync

def test_kuma_no_gitops_random_secret_by_default():
 docs=[x for x in yaml.safe_load_all(subprocess.check_output(['helm','template','uptime-kuma',str(ROOT/'charts/uptime-kuma')],text=True)) if x]
 assert not any(x['kind']=='Secret' for x in docs)
 assert next(x for x in docs if x['kind']=='Ingress')['spec']['rules'][0]['http']['paths'][0]['backend']['service']['name']=='public-web-kuma-proxy'
 assert len([x for x in docs if x['kind']=='Deployment'])==3
 assert any(x['kind']=='Deployment' and x['metadata']['name']=='public-web-kuma-proxy' for x in docs)


def test_schema_recovery_never_resets_existing_passwords_or_restarts_database():
    text=(ROOT/'scripts/kuma-db-account-recovery.py').read_text()
    assert 'CREATE USER' in text and 'ALTER USER' not in text and 'DROP USER' not in text
    assert 'rollout restart' not in text and "secret['metadata']['resourceVersion']" in text
    assert 'schema_grant.replace' in text and "--patch-file=/dev/stdin" in text
    assert 'Foreign/partial service account; stop' in text and 'uncertain.json' in text

def test_fresh_bootstrap_rejects_mismatched_application_identity():
    r=subprocess.run(['helm','template','uptime-kuma',str(ROOT/'charts/uptime-kuma'),'--set','database.bootstrapSecret=true'],text=True,capture_output=True)
    assert r.returncode!=0 and 'Fresh DB bootstrap requires' in r.stderr


def test_dns_cleanup_only_owned_files_and_no_global_flush_or_vpn_commands():
    text=(ROOT/'scripts/macos-public-dns-cleanup.py').read_text();m=module('macos-public-dns-cleanup')
    assert len(m.DOMAINS)==12 and all(x.endswith('.alchemmist.xyz') for x in m.DOMAINS)
    for forbidden in ['dscacheutil','killall','networksetup','netbird down','set State:/Network/Global/DNS']:
        assert forbidden not in text
    assert "['/bin/launchctl','bootout','system/'+LABEL]" in text
    assert 'Backup verification failed' in text and 'Fresh exact plan approval required' in text

def test_new_clients_do_not_reinstall_private_dns_by_default():
    defaults=yaml.safe_load((ROOT/'ansible/roles/wireguard_admin_client/defaults/main.yml').read_text())
    assert defaults['wireguard_admin_dns_mode']=='none'
    task=(ROOT/'ansible/roles/wiki_editor_client/tasks/main.yml').read_text()
    assert 'wiki_editor_client_private_dns_legacy | default(false)' in task
    assert 'include_tasks: legacy-resolver.yml' in task
