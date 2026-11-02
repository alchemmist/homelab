"""Проверки IAM: допуск в приложение не равен его внутренним полномочиям."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import subprocess
import runpy
import tempfile
import unittest
from urllib.request import Request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'ansible/roles/authentik/files'
sys.path.insert(0, str(FILES))
import app_iam
import lifecycle
import test_identity as identity


class LifecycleAPI:
    def __init__(self, fake):
        self.fake = fake
        self.writes = []

    def __call__(self, method, path, data=None):
        if method != 'GET':
            self.writes.append((method, path, data))
        if path.endswith(('/add_user/', '/remove_user/')):
            group_pk = path.split('/')[2]
            user = next(u for u in self.fake.data['core/users/'] if u['pk'] == data['pk'])
            group = next(g for g in self.fake.data['core/groups/'] if g['pk'] == group_pk)
            if path.endswith('/add_user/'):
                user['groups'].append(group_pk); group['users'].append(user['pk'])
            else:
                user['groups'].remove(group_pk); group['users'].remove(user['pk'])
            return None
        req = Request('https://example.invalid/api/v3/' + path, method=method,
                      data=json.dumps(data).encode() if data is not None else None)
        with self.fake(req) as response:
            return json.load(response)


class AppIAMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        helper = identity.IdentityTests(); helper.setup_root(root)
        self.reviewed = json.loads((ROOT / 'deploy/identity/account-mappings.json').read_text())
        self.fake = identity.FakeAuthentik(); helper.setup_reviewed(root, self.fake)
        helper.configure(root, self.fake)
        self.api = LifecycleAPI(self.fake)
        self.services = json.loads((root / 'services.json').read_text())
        self.manifest = json.loads((ROOT / 'deploy/identity/lifecycle.json').read_text())

    def plan(self):
        return lifecycle.build_plan(self.api, self.services, self.manifest, self.reviewed)

    def test_legacy_catalog_groups_are_known_without_human_grants(self):
        declared = set(app_iam.LEGACY_GROUPS) | set(app_iam.app_groups(self.services))
        for slug, service in self.services.items():
            self.assertLessEqual(set(app_iam.admission_groups(slug, service)), declared)
        teacher = next(g for g in self.fake.data['core/groups/'] if g['name'] == 'lms-teachers')
        self.assertFalse(teacher['is_superuser'])
        self.assertFalse(teacher.get('users', []))
        self.assertEqual(self.plan()['operations'], [])

    def test_default_manifest_has_no_grants_and_no_writes(self):
        self.assertEqual(self.plan()['operations'], [])
        self.assertEqual(self.api.writes, [])
        for group in self.fake.data['core/groups/']:
            if group['name'].startswith('app-'):
                self.assertFalse(group['is_superuser']); self.assertEqual(group['users'], [])

    def test_scoped_grant_remove_and_disabled_are_idempotent(self):
        tim = next(u for u in self.fake.data['core/users/'] if u['username'] == 'tim')
        before = list(tim['groups'])
        self.manifest['users']['tim']['appGroups'] = ['app-grafana-viewer', 'app-wiki-reader']
        plan = self.plan()
        self.assertEqual([o['action'] for o in plan['operations']], ['add', 'add'])
        lifecycle.apply_plan(self.api, plan, plan['sha256'])
        self.assertEqual(self.plan()['operations'], [])
        self.manifest['users']['tim'].update(state='disabled', appGroups=[])
        plan = self.plan()
        self.assertEqual([o['action'] for o in plan['operations']], ['disable', 'remove', 'remove'])
        lifecycle.apply_plan(self.api, plan, plan['sha256'])
        self.assertFalse(tim['is_active']); self.assertEqual(tim['groups'], before)
        self.assertEqual(self.plan()['operations'], [])
        # Legacy bootstrap never re-enables a disabled initialized account.
        identity.IdentityTests().configure(Path(self.temp.name), self.fake)
        self.assertFalse(tim['is_active'])

    def test_approval_hash_and_live_state_drift(self):
        plan = self.plan()
        with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
            lifecycle.apply_plan(self.api, plan, 'stale')
        tim = next(u for u in self.fake.data['core/users/'] if u['username'] == 'tim')
        tim['is_active'] = False
        self.assertNotEqual(plan['sha256'], self.plan()['sha256'])
        self.assertEqual(self.api.writes, [])

    def test_uuid_collision_and_email_do_not_link(self):
        self.fake.data['core/users/'][1]['uuid'] = 'e51e6956-16b5-455a-bbda-b73f96e85232'
        with self.assertRaisesRegex(RuntimeError, 'UUID required'):
            self.plan()
        before = len(self.fake.requests)
        with self.assertRaisesRegex(RuntimeError, 'UUID mismatch'):
            identity.IdentityTests().configure(Path(self.temp.name), self.fake)
        self.assertFalse(any(m != 'GET' for m, _, _, _ in self.fake.requests[before:]))

    def test_protected_owner_and_elevated_grants_refused(self):
        self.manifest['users']['alchemmist']['state'] = 'disabled'
        with self.assertRaisesRegex(RuntimeError, 'Owner'):
            self.plan()
        self.manifest['users']['alchemmist']['state'] = 'preserve'
        self.manifest['users']['tim']['appGroups'] = ['homelab-owner']
        with self.assertRaisesRegex(RuntimeError, 'declared app groups'):
            self.plan()
        self.assertEqual(self.api.writes, [])

    def test_unsupported_native_role_and_machine_account_refused(self):
        self.manifest['users']['tim']['appGroups'] = ['app-rancher-user']
        with self.assertRaisesRegex(RuntimeError, 'not ready'):
            self.plan()
        self.manifest['users']['tim']['appGroups'] = []
        self.fake.data['core/users/'][1]['type'] = 'service_account'
        with self.assertRaisesRegex(RuntimeError, 'service/external'):
            self.plan()

    def test_app_group_inheritance_or_superuser_refused(self):
        group = next(g for g in self.fake.data['core/groups/'] if g['name'] == 'app-grafana-viewer')
        owner = next(g for g in self.fake.data['core/groups/'] if g['name'] == 'homelab-owner')
        rbac = {'pk': 'rbac-ancestor', 'name': 'rbac-ancestor', 'is_superuser': False,
                'parents': [], 'roles': ['admin-role'], 'attributes': {}, 'users': []}
        self.fake.data['core/groups/'].append(rbac)
        self.manifest['users']['tim']['appGroups'] = ['app-grafana-viewer']
        for field, value in [('parents', [owner['pk']]), ('parents', [rbac['pk']]),
                             ('is_superuser', True), ('roles', ['admin-role'])]:
            old = copy.deepcopy(group); group[field] = value
            with self.assertRaisesRegex(RuntimeError, 'non-superuser'):
                self.plan()
            self.assertEqual(self.api.writes, [])
            group.clear(); group.update(old)

    def test_incomplete_current_group_schema_refused_before_assignment(self):
        group = next(g for g in self.fake.data['core/groups/'] if g['name'] == 'app-grafana-viewer')
        self.manifest['users']['tim']['appGroups'] = ['app-grafana-viewer']
        for field in ['parents', 'roles', 'is_superuser']:
            for value in ['missing', None, {}, '', 0]:
                old = copy.deepcopy(group)
                if value == 'missing':
                    group.pop(field)
                else:
                    group[field] = value
                with self.subTest(field=field, value=value), self.assertRaisesRegex(RuntimeError, 'non-superuser'):
                    self.plan()
                self.assertEqual(self.api.writes, [])
                group.clear(); group.update(old)

    def test_binding_drift_is_not_silently_reset(self):
        binding = self.fake.data['policies/bindings/'][0]
        for change in [{'enabled': False}, {'negate': True}, {'group': 'unknown-group'}, {'user': 6}]:
            old = copy.deepcopy(binding); binding.update(change)
            with self.assertRaisesRegex(RuntimeError, 'binding drift'):
                self.plan()
            with self.assertRaisesRegex(RuntimeError, 'binding drift'):
                identity.IdentityTests().configure(Path(self.temp.name), self.fake)
            self.assertEqual(binding, {**old, **change})
            binding.clear(); binding.update(old)

    def test_missing_user_is_not_created_and_omission_is_not_revocation(self):
        self.fake.data['core/users/'].pop()
        with self.assertRaisesRegex(RuntimeError, 'existing username'):
            self.plan()
        before = len(self.fake.requests)
        with self.assertRaisesRegex(RuntimeError, 'instead of recreating'):
            identity.IdentityTests().configure(Path(self.temp.name), self.fake)
        self.assertFalse(any(m != 'GET' for m, _, _, _ in self.fake.requests[before:]))
        del self.manifest['users']['tim']
        self.assertEqual(self.plan()['operations'], [])
        self.assertEqual(self.api.writes, [])

    def test_foreign_app_group_is_not_adopted(self):
        group = next(g for g in self.fake.data['core/groups/'] if g['name'] == 'app-grafana-viewer')
        group['attributes'] = {}
        with self.assertRaisesRegex(RuntimeError, 'unmarked app group'):
            self.plan()
        with self.assertRaisesRegex(RuntimeError, 'unmarked app group'):
            identity.IdentityTests().configure(Path(self.temp.name), self.fake)

    def test_policy_mode_is_not_silently_reset(self):
        self.fake.data['core/applications/'][0]['policy_engine_mode'] = 'all'
        with self.assertRaisesRegex(RuntimeError, 'mode drift'):
            self.plan()
        with self.assertRaisesRegex(RuntimeError, 'mode drift'):
            identity.IdentityTests().configure(Path(self.temp.name), self.fake)

    def test_pagination_and_binding_duplicates(self):
        calls = []
        def api(method, path):
            calls.append(path)
            page = len(calls)
            return {'results': [page], 'pagination': {'next': page == 1}}
        self.assertEqual(app_iam.rows(api, 'core/groups/'), [1, 2])
        self.assertIn('page=2', calls[-1])
        with self.assertRaisesRegex(RuntimeError, 'binding drift'):
            app_iam.validate_bindings([{'group': 'a'}, {'group': 'a'}], {'a'})

    def test_wiki_integration_keeps_exact_links_and_overrides(self):
        writes = []
        def run(args, **kwargs):
            if 'apply' in args:
                writes.append(json.loads(kwargs['input']))
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch('sys.argv', ['integrate.py', self.temp.name, 'wiki']), \
             patch('urllib.request.urlopen', self.fake), patch('subprocess.run', run), \
             contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(ROOT / 'ansible/roles/identity_integrations/files/integrate.py'), run_name='__main__')
        self.assertEqual(len(writes), 1)
        data = writes[0]['stringData']
        self.assertEqual(json.loads(data['WIKI_OIDC_LINKS']),
                         {a['idpUserUuid']: a['wikiUserId'] for a in self.reviewed.values()})
        self.assertEqual(json.loads(data['WIKI_OIDC_SUBJECT_ROLES']),
                         {a['idpUserUuid']: a['wikiRole'] for a in self.reviewed.values()})
        self.assertEqual(json.loads(data['WIKI_OIDC_GROUP_ROLES'])['app-wiki-editor'], 'editor')
        # A same-name/email replacement must not rewrite any native link.
        self.fake.data['core/users/'][1]['uuid'] = 'e51e6956-16b5-455a-bbda-b73f96e85232'
        with patch('sys.argv', ['integrate.py', self.temp.name, 'wiki']), \
             patch('urllib.request.urlopen', self.fake), patch('subprocess.run') as kube, \
             self.assertRaisesRegex(RuntimeError, 'subject mismatch'):
            runpy.run_path(str(ROOT / 'ansible/roles/identity_integrations/files/integrate.py'), run_name='__main__')
        kube.assert_not_called()

    def test_native_role_boundaries_and_subject_overrides_preserved(self):
        import yaml
        env = yaml.safe_load((ROOT / 'deploy/identity/grafana-oidc-values.yaml').read_text())['grafana']['env']
        expression = env['GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH']
        self.assertTrue(expression.startswith("contains(groups[*], 'homelab-owner') && 'GrafanaAdmin'"))
        self.assertIn("'app-grafana-editor') && 'Editor'", expression)
        webui = json.loads((ROOT / 'deploy/identity/open-webui-env.json').read_text())
        self.assertEqual(webui['OAUTH_ADMIN_ROLES'], 'homelab-owner')
        self.assertEqual(webui['OAUTH_MERGE_ACCOUNTS_BY_EMAIL'], 'False')
        self.assertIn('app-open-webui-user', webui['OAUTH_ALLOWED_ROLES'])
        self.assertEqual(self.reviewed['tim']['wikiRole'], 'editor')
        self.assertEqual(self.reviewed['alchemmist']['idpUserUuid'], self.manifest['users']['alchemmist']['uuid'])
        for provider in self.fake.data['providers/oauth2/']:
            self.assertEqual(provider['authorization_flow'], 'default-provider-authorization-explicit-consent')
            self.assertEqual(provider['authentication_flow'], 'default-authentication-flow')
            self.assertEqual(provider['sub_mode'], self.services[provider['name'][8:]].get('subMode', 'hashed_user_id'))
        scope = next(s for s in self.fake.data['propertymappings/provider/scope/'] if s.get('name') == 'homelab-groups')
        self.assertEqual(scope['expression'], 'return {"groups": [group.name for group in request.user.ak_groups.all()]}')


if __name__ == '__main__':
    unittest.main()
