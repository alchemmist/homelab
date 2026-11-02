import contextlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ansible/roles/authentik/files'))
from app_iam import admission_groups

class FakeAuthentik:
    def __init__(self):
        self.data={
            'core/groups/':[], 'core/users/':[], 'providers/oauth2/':[],
            'core/applications/':[], 'policies/bindings/':[], 'providers/proxy/':[],
            'outposts/instances/':[{'pk':'embedded','managed':'goauthentik.io/outposts/embedded','config':{},'providers':[]}],
            'stages/authenticator/validate/':[{'pk':'validate','name':'default-authentication-mfa-validation'}],
            'stages/authenticator/totp/':[{'pk':'totp','name':'default-authenticator-totp-setup'}],
            'flows/instances/':[{'pk':s,'slug':s} for s in [
                'default-authentication-flow','default-provider-authorization-explicit-consent',
                'default-provider-invalidation-flow','default-provider-authorization-implicit-consent']],
            'crypto/certificatekeypairs/':[{'pk':'cert','name':'authentik Self-signed Certificate'}],
            'propertymappings/provider/scope/':[{'pk':s,'scope_name':s} for s in ['openid','profile','email','offline_access']]}
        self.requests=[]

    def __call__(self,req,timeout=60):
        uri=urlparse(req.full_url);path=uri.path.split('/api/v3/')[1]
        method=req.get_method();payload=json.loads(req.data) if req.data else None
        self.requests.append((method,path,payload,parse_qs(uri.query)))
        if method=='GET':
            rows=self.data[path]
            for k,vs in parse_qs(uri.query).items():
                if k in ['name','username','slug','target']:rows=[r for r in rows if str(r.get(k))==vs[0]]
            return io.BytesIO(json.dumps({'results':rows}).encode())
        if path.endswith('/set_password/'):return io.BytesIO(b'{}')
        if method=='POST':
            row={'pk':len(self.data[path])+1,**payload}
            if path=='core/groups/':
                # Current 2026.8.5 GroupSerializer defaults, including M2M parents.
                row={'attributes':{},'is_superuser':False,'parents':[],'roles':[],
                     'users':[],**row}
                row['pk']='group-'+str(row['pk'])
            if path=='core/users/':
                known=json.loads((ROOT/'deploy/identity/account-mappings.json').read_text())
                row['uuid']=known.get(row['username'],{}).get('idpUserUuid','test-new-subject')
                row['is_superuser']=False
                for g in self.data['core/groups/']:
                    if g['pk'] in payload.get('groups',[]):g['users'].append(row['pk'])
            self.data[path].append(row)
        else:
            parent,pk,_=path.rsplit('/',2);parent+='/'
            row=next(r for r in self.data[parent] if str(r['slug'] if parent=='core/applications/' else r['pk'])==pk)
            row.update(payload)
        return io.BytesIO(json.dumps(row).encode())

class IdentityTests(unittest.TestCase):
    def configure(self,root,api):
        with patch('sys.argv',['configure.py',str(root)]),patch('urllib.request.urlopen',api),contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(ROOT/'ansible/roles/authentik/files/configure.py'),run_name='__main__')

    def setup_root(self,root):
        (root/'credentials.json').write_text(json.dumps({'AUTHENTIK_BOOTSTRAP_TOKEN':'fake-test-token'}))
        (root/'services.json').write_text((ROOT/'deploy/identity/services.json').read_text())

    def setup_reviewed(self,root,api):
        # Restored current identities, not speculative/future users.
        self.configure(root,api)
        accounts=json.loads((ROOT/'deploy/identity/account-mappings.json').read_text())
        observer=next(g for g in api.data['core/groups/'] if g['name']=='homelab-observer')
        api.data['core/users/'].append({'pk':6,'uuid':accounts['tim']['idpUserUuid'],
            'username':'tim','email':accounts['tim']['email'],'is_active':True,
            'is_superuser':False,'groups':[observer['pk']]})
        observer['users'].append(6)
        (root/'tim-login.json').write_text(json.dumps({'initialized':True}))
        (root/'tim-login.json').chmod(0o600)
        (root/'account-mappings.json').write_text(json.dumps(accounts))

    def test_configuration_idempotent_and_mfa_required(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root);api=FakeAuthentik()
            self.configure(root,api)
            clients=(root/'oidc-clients.json').read_bytes();owner=(root/'owner-login.json').read_bytes()
            self.configure(root,api)
            self.assertEqual((root/'oidc-clients.json').read_bytes(),clients)
            self.assertEqual((root/'owner-login.json').read_bytes(),owner)
            self.assertEqual(len(api.data['core/users/']),1)
            self.assertEqual(api.data['core/users/'][0]['username'],'alchemmist')
            privileged=[g['name'] for g in api.data['core/groups/'] if g['is_superuser']]
            self.assertEqual(privileged,['homelab-owner'])
            self.assertEqual(api.data['stages/authenticator/validate/'][0]['not_configured_action'],'configure')
            for provider in api.data['providers/oauth2/']:
                self.assertEqual(provider['grant_types'],['authorization_code','refresh_token'])
            grafana=next(p for p in api.data['providers/oauth2/'] if p['name']=='homelab-grafana')
            self.assertIn('offline_access', grafana['property_mappings'])
            self.assertEqual(len(api.data['core/applications/']),8)
            self.assertEqual(len(api.data['policies/bindings/']),sum(len(admission_groups(slug,service)) for slug,service in json.loads((root/'services.json').read_text()).items() if slug!='litellm'))
            for method,path,body,query in api.requests:
                if method=='GET' and path=='core/applications/':
                    self.assertEqual(query['superuser_full_list'],['true'])
            self.assertEqual((root/'owner-login.json').stat().st_mode & 0o777,0o600)
            self.assertEqual((root/'oidc-clients.json').stat().st_mode & 0o777,0o600)

    def test_existing_litellm_custom_scope_survives_foundation_replay(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root);api=FakeAuthentik()
            api.data['propertymappings/provider/scope/'].append({'pk':'litellm-identity','name':'homelab-litellm-reviewed-identity','scope_name':'litellm_identity'})
            self.configure(root,api);self.configure(root,api)
            provider=next(p for p in api.data['providers/oauth2/'] if p['name']=='homelab-litellm')
            self.assertIn('litellm-identity',provider['property_mappings'])
            self.assertEqual(len(api.data['core/applications/']),9)

    def test_existing_owner_never_silently_taken_over(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root);api=FakeAuthentik()
            api.data['core/users/']=[{'pk':42,'username':'alchemmist'}]
            with self.assertRaisesRegex(RuntimeError,'already exists'):
                self.configure(root,api)
            self.assertFalse(any(path.endswith('/set_password/') for _,path,_,_ in api.requests))

    def test_missing_provider_credentials_refuses_rotation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root);api=FakeAuthentik()
            self.configure(root,api);(root/'oidc-clients.json').unlink()
            with self.assertRaisesRegex(RuntimeError,'refusing rotation'):self.configure(root,api)

    def test_unexpected_owner_member_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_root(root);api=FakeAuthentik()
            self.configure(root,api)
            group=next(g for g in api.data['core/groups/'] if g['name']=='homelab-owner')
            group['users'].append(999);group['is_superuser']=False
            with self.assertRaisesRegex(RuntimeError,'Unexpected owner'):self.configure(root,api)
            self.assertFalse(group['is_superuser'])

    def test_runtime_is_not_a_cluster_administrator(self):
        values=yaml.safe_load((ROOT/'deploy/authentik/values.yaml').read_text())
        self.assertFalse(values['serviceAccount']['create'])
        for name in ['server','worker']:
            self.assertFalse(values[name]['automountServiceAccountToken'])
            self.assertTrue(values[name]['resources']['limits']['memory'])
        self.assertFalse(values['postgresql']['enabled'])
        self.assertNotIn('secret_key',values['authentik'])

    def test_world_readable_primary_kubeconfig_not_reintroduced(self):
        source=(ROOT/'ansible/roles/k3s_ha/templates/config.yaml.j2').read_text()
        self.assertNotIn("'0644'",source)
        self.assertIn('write-kubeconfig-group: alchemmist',source)
        install=(ROOT/'ansible/playbooks/k3s.yml').read_text()
        self.assertNotIn('--write-kubeconfig-mode 644',install)

    def test_personal_keys_replaced_not_appended(self):
        tasks=yaml.safe_load((ROOT/'ansible/roles/users/tasks/main.yml').read_text())
        key_task=next(t for t in tasks if 'Replace managed key sets' in t['name'])
        self.assertIn('ansible.builtin.copy',key_task)
        self.assertNotIn('ansible.builtin.lineinfile',key_task)
        self.assertIn("'disabled'",key_task['ansible.builtin.copy']['content'])

    def test_grafana_keeps_local_login_and_uses_secret_reference(self):
        v=yaml.safe_load((ROOT/'deploy/identity/grafana-oidc-values.yaml').read_text())['grafana']
        self.assertNotIn('GF_AUTH_DISABLE_LOGIN_FORM',v['env'])
        self.assertEqual(v['env']['GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN'],'false')
        self.assertNotIn('GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET',v['env'])
        self.assertEqual(v['envValueFrom']['GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET']['secretKeyRef']['name'],'socrat-authentik-grafana')

class RolloutRegressionTests(unittest.TestCase):
    def test_pinned_icons_match_local_portal_assets(self):
        import hashlib,xml.etree.ElementTree as ET
        manifest=json.loads((ROOT/'assets/service-icons/sources.json').read_text())
        services=json.loads((ROOT/'deploy/identity/services.json').read_text())
        self.assertEqual(len(services),9)
        for slug,service in services.items():
            data=(ROOT/'assets/service-icons'/f'{slug}.svg').read_bytes()
            digest=hashlib.sha256(data).hexdigest()
            self.assertEqual(digest,manifest['files'][f'{slug}.svg']['sha256'])
            self.assertEqual(service['icon'],f'service-icons/{slug}-{digest[:12]}.svg')
            for node in ET.fromstring(data).iter():
                self.assertNotIn(node.tag.split('}')[-1],['script','foreignObject'])
                self.assertFalse(any(k.lower().startswith('on') for k in node.attrib))

    def test_reviewed_human_reconciliation_keeps_tim_non_privileged(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);helper=IdentityTests();helper.setup_root(root);api=FakeAuthentik()
            helper.setup_reviewed(root,api)
            helper.configure(root,api);helper.configure(root,api)
            self.assertEqual(len(api.data['core/users/']),2)
            owner_group=next(g for g in api.data['core/groups/'] if g['name']=='homelab-owner')
            tim=next(u for u in api.data['core/users/'] if u['username']=='tim')
            self.assertNotIn(owner_group['pk'],tim['groups'])
            self.assertNotIn(tim['pk'],owner_group['users'])
            self.assertEqual((root/'tim-login.json').stat().st_mode & 0o777,0o600)

    def test_n8n_gate_does_not_capture_machine_traffic_or_claim_native_sso(self):
        import re
        services=json.loads((ROOT/'deploy/identity/services.json').read_text())
        pattern=re.compile(services['n8n']['proxy']['skipPathRegex'])
        for path in ['/healthz','/webhook/a','/api/v1/workflows','/form/a']:
            self.assertIsNotNone(pattern.match(path))
        for path in ['/','/rest/login','/rest/settings','/webhookevil/secret']:
            self.assertIsNone(pattern.match(path))
        ui,machine=list(yaml.safe_load_all((ROOT/'deploy/identity/n8n-gateway.yaml').read_text()))
        self.assertGreater(int(machine['metadata']['annotations']['traefik.ingress.kubernetes.io/router.priority']),
                           int(ui['metadata']['annotations']['traefik.ingress.kubernetes.io/router.priority']))
        self.assertEqual(machine['metadata']['namespace'],'automation')
        for path in machine['spec']['rules'][0]['http']['paths']:
            self.assertEqual(path['backend']['service']['name'],'n8n')
            self.assertNotEqual(path['path'],'/')
        self.assertIn('native-sso-requires-license',services['n8n']['migration'])

    def test_owner_mapping_is_server_admin_only_for_owner_group(self):
        env=yaml.safe_load((ROOT/'deploy/identity/grafana-oidc-values.yaml').read_text())['grafana']['env']
        self.assertEqual(env['GF_AUTH_GENERIC_OAUTH_ALLOW_ASSIGN_GRAFANA_ADMIN'],'true')
        self.assertEqual(env['GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH'],
            "contains(groups[*], 'homelab-owner') && 'GrafanaAdmin' || contains(groups[*], 'app-grafana-editor') && 'Editor' || 'Viewer'")
        self.assertIn('offline_access', env['GF_AUTH_GENERIC_OAUTH_SCOPES'].split())
        self.assertEqual(env['GF_AUTH_GENERIC_OAUTH_USE_REFRESH_TOKEN'], 'true')
        self.assertEqual(env['GF_AUTH_LOGIN_MAXIMUM_LIFETIME_DURATION'], '8h')
        webui=json.loads((ROOT/'deploy/identity/open-webui-env.json').read_text())
        self.assertEqual(webui['OAUTH_MERGE_ACCOUNTS_BY_EMAIL'],'False')
        self.assertEqual(webui['OAUTH_ADMIN_ROLES'],'homelab-owner')

    def test_sudo_listing_rc_zero_is_not_a_privilege_grant(self):
        from types import SimpleNamespace
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'.ssh').mkdir();(Path(d)/'.ssh/authorized_keys').write_text('key1\nkey2\n')
            def run(args,**kwargs):
                if '-T' in args:return subprocess.CompletedProcess(args,0,'\x1b]3008;test\x1b\\pubkeyauthentication yes\nusepam yes\n','')
                if args[0]=='sudo':return subprocess.CompletedProcess(args,0,'User tim is not allowed to run sudo on socrat-0.\n','')
                return subprocess.CompletedProcess(args,1,'','')
            output=io.StringIO()
            with patch('sys.argv',['verify.py','tim']),patch('pwd.getpwnam',return_value=SimpleNamespace(pw_dir=d,pw_shell='/bin/bash')),patch('subprocess.run',run),patch('shutil.which',return_value='/usr/sbin/sshd'),contextlib.redirect_stdout(output):
                runpy.run_path(str(ROOT/'ansible/roles/users/files/verify.py'),run_name='__main__')
            result=json.loads(output.getvalue())
            self.assertFalse(result['hasSudoGrant']);self.assertFalse(result['canReadAdminKubeconfig'])
            self.assertEqual(result['pubkeyAuthentication'],'yes');self.assertEqual(result['usePAM'],'yes')

if __name__=='__main__':unittest.main()
