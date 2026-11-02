"""Create-only preparation against current explicit Group/Binding schema; no live API."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ansible/roles/authentik/files'))
import prepare_app_iam as prep


class FakeAPI:
    def __init__(self, services, reviewed):
        self.data = {p: [] for p in prep.COLLECTIONS}
        self.requests = []
        self.page_size = 2
        self.fail_write = None
        self.after_get = None
        self.writes = 0
        legacy = sorted({g for s in services.values() for g in s.get('groups', [])})
        self.data['core/groups/'] = [dict(prep.group_payload(n), pk='g-' + n) for n in legacy]
        for i, (n, uuid) in enumerate(prep.PINNED.items()):
            self.data['core/users/'].append({'pk': i + 1, 'username': n, 'uuid': uuid,
                'groups': ['g-' + g for g in reviewed[n]['groups']], 'type': 'internal',
                'is_active': True, 'is_superuser': n == 'alchemmist'})
        for slug in prep.ALLOWLIST:
            provider = {'pk': len(self.data['providers/all/']) + 1, 'name': 'homelab-' + slug}
            self.data['providers/all/'].append(provider)
            self.data['providers/oauth2/'].append(dict(provider, client_secret='SECRET-NEVER-LOG'))
            app = {'pk': 'a-' + slug, 'slug': slug, 'provider': provider['pk'], 'policy_engine_mode': 'any'}
            self.data['core/applications/'].append(app)
            for n in services[slug]['groups']:
                self.data['policies/bindings/'].append({'pk': 'b-' + str(len(self.data['policies/bindings/'])),
                    'target': app['pk'], 'group': 'g-' + n, 'user': None, 'policy': None,
                    'enabled': True, 'negate': False, 'failure_result': False, 'order': 0})
        for p in prep.COLLECTIONS:
            if p.startswith(('stages/', 'flows/', 'outposts/', 'propertymappings/')):
                self.data[p] = [{'pk': 'protected-' + p, 'setting': 'unchanged'}]

    def __call__(self, method, endpoint, payload=None):
        self.requests.append((method, endpoint, copy.deepcopy(payload)))
        parsed = urlsplit(endpoint)
        path = parsed.path
        if method == 'GET':
            if self.after_get:
                self.after_get(path)
            page = int(parse_qs(parsed.query)['page'][0])
            start = (page - 1) * self.page_size
            data = self.data[path]
            return {'results': copy.deepcopy(data[start:start + self.page_size]),
                    'pagination': {'next': page + 1 if start + self.page_size < len(data) else 0}}
        assert method == 'POST' and path in ('core/groups/', 'policies/bindings/')
        self.writes += 1
        if self.fail_write == self.writes:
            raise RuntimeError('simulated private failure')
        created = dict(payload, pk='created-' + str(self.writes))
        if path == 'policies/bindings/':
            created.update(user=None, policy=None)
        self.data[path].append(created)
        return copy.deepcopy(created)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.services = json.loads((ROOT / 'deploy/identity/services.json').read_text())
        self.reviewed = json.loads((ROOT / 'deploy/identity/account-mappings.json').read_text())
        self.api = FakeAPI(self.services, self.reviewed)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.evidence = {'version': 1, 'reviewed_commit': 'a' * 40,
            'reviewed_tool_sha256': prep.tool_hash(), 'backup_sha256': 'b' * 64,
            'restore_test_sha256': 'c' * 64, 'recovery_owner': 'operator',
            'change_window': 'reviewed window', 'writers_paused': True}

    def plan(self, stage='groups-only', evidence=None):
        return prep.build_plan(self.api, self.services, self.reviewed, stage, evidence)[0]

    def apply(self, stage='groups-only', approval=None):
        if approval is None:
            approval = self.plan(stage, self.evidence)['sha256']
        with prep.locked(self.root):
            return prep.apply_plan(self.api, self.root, self.services, self.reviewed,
                                   stage, self.evidence, approval)

    def test_full_plan_is_get_only_paginated_and_sanitized(self):
        before = copy.deepcopy(self.api.data)
        plan = self.plan()
        self.assertEqual(len(plan['operations']), 9)
        self.assertEqual(before, self.api.data)
        self.assertEqual({m for m, _, _ in self.api.requests}, {'GET'})
        self.assertTrue(any('page=2' in p for _, p, _ in self.api.requests))
        self.assertEqual(set(plan['snapshot_hashes']), set(prep.COLLECTIONS))
        self.assertNotIn('SECRET', json.dumps(plan))
        for op in plan['operations']:
            self.assertEqual(op['payload'], prep.group_payload(op['payload']['name']))

    def test_both_stages_bounded_preserve_everything_else(self):
        before = copy.deepcopy(self.api.data)
        self.assertEqual(self.apply(), 9)
        self.assertEqual(self.plan()['operations'], [])
        for p in prep.COLLECTIONS:
            if p != 'core/groups/':
                self.assertEqual(self.api.data[p], before[p])
        plan = self.plan('groups+empty-bindings')
        self.assertEqual(len(plan['operations']), 9)
        for op in plan['operations']:
            self.assertIn(op['payload']['group'], {g['pk'] for g in self.api.data['core/groups/']})
            self.assertIn(op['payload']['target'], {a['pk'] for a in self.api.data['core/applications/']})
        self.assertEqual(self.apply('groups+empty-bindings'), 9)
        self.assertEqual(self.plan('groups+empty-bindings')['operations'], [])
        for p in prep.COLLECTIONS:
            if p not in ('core/groups/', 'policies/bindings/'):
                self.assertEqual(self.api.data[p], before[p])
        self.assertEqual(self.api.data['policies/bindings/'][:len(before['policies/bindings/'])],
                         before['policies/bindings/'])
        for method, path, payload in self.api.requests:
            if method != 'GET':
                self.assertEqual(method, 'POST')
                self.assertIn(path, ('core/groups/', 'policies/bindings/'))
        for p in (self.root / 'app-iam-prepare-journal').rglob('*'):
            self.assertEqual(p.stat().st_mode & 0o077, 0)
        self.assertNotIn('SECRET', ''.join(p.read_text() for p in self.root.rglob('*.json')))

    def test_stage_b_requires_real_fresh_group_pks(self):
        with self.assertRaisesRegex(RuntimeError, 'groups-only first'):
            self.plan('groups+empty-bindings')
        self.assertEqual(self.api.writes, 0)

    def test_group_schema_all_relations_required_and_no_adoption(self):
        self.apply()
        group = next(g for g in self.api.data['core/groups/'] if g['name'].startswith('app-'))
        good = copy.deepcopy(group)
        for field in ('parents', 'children', 'users', 'roles', 'is_superuser', 'attributes'):
            for value in ('missing', None, ['unexpected'], True):
                with self.subTest(field=field, value=value):
                    group.clear(); group.update(good)
                    if value == 'missing':
                        group.pop(field)
                    else:
                        group[field] = value
                    with self.assertRaises(RuntimeError):
                        self.plan()
        group.clear(); group.update(good)
        self.api.data['core/users/'][0]['groups'].append(group['pk'])
        with self.assertRaisesRegex(RuntimeError, 'membership'):
            self.plan()

    def test_unexpected_objects_catalog_uuids_and_links_fail_closed(self):
        baseline = copy.deepcopy(self.api.data)
        changes = [
            lambda: self.api.data['core/groups/'].append(dict(prep.group_payload('app-foreign-user'), pk='foreign')),
            lambda: self.api.data['core/groups/'].append(copy.deepcopy(self.api.data['core/groups/'][0])),
            lambda: self.api.data['core/users/'][0].update(uuid='wrong'),
            lambda: self.api.data['core/users/'][1].update(is_superuser=True),
            lambda: self.api.data['core/users/'][0].update(is_active=False),
            lambda: self.api.data['core/applications/'][0].update(policy_engine_mode='all'),
            lambda: self.api.data['core/applications/'][0].update(provider=999),
            lambda: self.api.data['core/applications/'].pop(),
        ]
        for change in changes:
            self.api.data = copy.deepcopy(baseline)
            change()
            with self.assertRaises(RuntimeError):
                self.plan()
        self.api.data = baseline
        self.services['grafana']['appRoles']['admin'] = {}
        with self.assertRaisesRegex(RuntimeError, 'allowlist'):
            self.plan()
        self.assertEqual(self.api.writes, 0)

    def test_binding_faults_in_both_stages(self):
        self.apply()
        binding = self.api.data['policies/bindings/'][0]
        good = copy.deepcopy(binding)
        for field, value in [('group', 'unknown'), ('user', 3), ('policy', 'policy'),
                             ('enabled', False), ('enabled', 1), ('negate', True),
                             ('failure_result', True), ('policy', 'missing')]:
            binding.clear(); binding.update(good)
            if value == 'missing':
                binding.pop(field)
            else:
                binding[field] = value
            for stage in ('groups-only', 'groups+empty-bindings'):
                with self.subTest(field=field, stage=stage), self.assertRaises(RuntimeError):
                    self.plan(stage)
        binding.clear(); binding.update(good)
        self.api.data['policies/bindings/'].append(dict(good, pk='duplicate'))
        with self.assertRaises(RuntimeError):
            self.plan()

    def test_protected_drift_invalidates_approval_without_any_write(self):
        baseline = copy.deepcopy(self.api.data)
        for path in prep.COLLECTIONS:
            self.api.data = copy.deepcopy(baseline)
            plan = self.plan(evidence=self.evidence)
            if not self.api.data[path]:
                self.api.data[path].append({'pk': 'new-protected'})
            else:
                self.api.data[path][0]['unrelated-setting'] = 'drift'
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                self.apply(approval=plan['sha256'])
        self.assertEqual(self.api.writes, 0)

    def test_drift_during_second_snapshot_prevents_first_write(self):
        approval = self.plan(evidence=self.evidence)['sha256']
        def drift(path):
            # One page per empty proxy collection: second pass is pre-write revalidation.
            if path == 'providers/proxy/':
                drift.count += 1
                if drift.count == 2:
                    self.api.data['outposts/instances/'][0]['setting'] = 'drift'
        drift.count = 0
        self.api.after_get = drift
        with self.assertRaisesRegex(RuntimeError, 'Baseline drift'):
            self.apply(approval=approval)
        self.assertEqual(self.api.writes, 0)

    def test_partial_failure_durable_pending_and_no_retry_rollback_or_adoption(self):
        self.api.fail_write = 2
        with self.assertRaisesRegex(RuntimeError, 'simulated'):
            self.apply()
        journals = list((self.root / 'app-iam-prepare-journal').iterdir())
        self.assertEqual(len(journals), 1)
        self.assertEqual(json.loads((journals[0] / '01.json').read_text())['status'], 'verified')
        self.assertEqual(json.loads((journals[0] / '02.json').read_text())['status'], 'pending')
        self.assertEqual(json.loads((journals[0] / 'run.json').read_text())['status'], 'stopped-uncertain')
        self.api.fail_write = None
        with self.assertRaisesRegex(RuntimeError, 'Unresolved prior journal'):
            self.apply()
        self.assertEqual(self.api.writes, 2)

    def test_uncertain_accepted_post_is_not_retried_or_adopted(self):
        original = self.api.__call__
        def uncertain(method, path, payload=None):
            result = original(method, path, payload)
            if method == 'POST':
                raise RuntimeError('connection lost after server accepted POST')
            return result
        approval = self.plan(evidence=self.evidence)['sha256']
        with prep.locked(self.root), self.assertRaises(RuntimeError):
            prep.apply_plan(uncertain, self.root, self.services, self.reviewed,
                            'groups-only', self.evidence, approval)
        self.assertEqual(self.api.writes, 1)
        self.assertEqual(len(self.plan()['operations']), 8)
        with self.assertRaisesRegex(RuntimeError, 'Unresolved prior journal'):
            self.apply()
        self.assertEqual(self.api.writes, 1)
        entry = next((self.root / 'app-iam-prepare-journal').glob('*/01.json'))
        self.assertEqual(json.loads(entry.read_text())['status'], 'pending')

    def test_journal_intent_failure_prevents_post(self):
        original = prep.atomic_json
        def fail_intent(path, value):
            if path.name == '01.json':
                raise OSError('disk full')
            return original(path, value)
        with patch.object(prep, 'atomic_json', side_effect=fail_intent), self.assertRaises(OSError):
            self.apply()
        self.assertEqual(self.api.writes, 0)

    def test_post_create_drift_stops_after_one_post(self):
        original = self.api.__call__
        def api(method, path, payload=None):
            result = original(method, path, payload)
            if method == 'POST':
                self.api.data['outposts/instances/'][0]['setting'] = 'drift'
            return result
        approval = self.plan(evidence=self.evidence)['sha256']
        with prep.locked(self.root), self.assertRaisesRegex(RuntimeError, 'post-create drift'):
            prep.apply_plan(api, self.root, self.services, self.reviewed, 'groups-only', self.evidence, approval)
        self.assertEqual(self.api.writes, 1)

    def test_pagination_missing_cursor_arbitrary_url_and_duplicate_rows_refused(self):
        for response in ({'results': []}, {'results': [], 'pagination': {}},
                         {'results': [], 'pagination': {'next': 'https://evil.invalid/'}},
                         {'results': [], 'pagination': {'next': True}}):
            with self.assertRaises(RuntimeError):
                prep.rows(lambda *args: response, 'core/users/')
        original = self.api.__call__
        def api(method, path, payload=None):
            result = original(method, path, payload)
            if 'core/users/' in path:
                result['results'] *= 2
            return result
        with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
            prep.snapshot(api)

    def test_private_credentials_alias_tls_redirect_and_request_boundary(self):
        path = self.root / 'credentials.json'
        for key in ('AUTHENTIK_API_TOKEN', 'AUTHENTIK_BOOTSTRAP_TOKEN'):
            path.write_text(json.dumps({key: 'PRIVATE-TOKEN'})); path.chmod(0o600)
            opener = unittest.mock.Mock()
            opener.open.return_value = contextlib.closing(io.BytesIO(b'{"results": []}'))
            with patch('urllib.request.build_opener', return_value=opener) as build:
                api = prep.api_for(self.root)
                api('GET', 'core/users/?page=1')
                request = opener.open.call_args.args[0]
                self.assertTrue(request.full_url.startswith('https://'))
                self.assertEqual(request.get_header('Authorization'), 'Bearer PRIVATE-TOKEN')
                self.assertIsInstance(build.call_args.args[0], prep.NoRedirect)
                opener.open.side_effect = HTTPError('https://example.invalid/', 403,
                    'PRIVATE-TOKEN', {}, io.BytesIO(b'SECRET-RESPONSE-BODY'))
                with self.assertRaisesRegex(RuntimeError, '^API request failed; outcome may be uncertain$'):
                    api('GET', 'core/users/?page=1')
                for method, endpoint in [('PATCH', 'core/groups/'), ('DELETE', 'core/users/'),
                                         ('POST', 'core/users/'), ('POST', 'outposts/instances/')]:
                    with self.assertRaises(RuntimeError):
                        api(method, endpoint, {})
        with self.assertRaises(RuntimeError):
            prep.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid/')
        path.chmod(0o644)
        with self.assertRaises(RuntimeError):
            prep.api_for(self.root)
        path.chmod(0o600)
        path.write_text(json.dumps({'AUTHENTIK_API_TOKEN': 'one', 'AUTHENTIK_BOOTSTRAP_TOKEN': 'two'}))
        with self.assertRaises(RuntimeError):
            prep.api_for(self.root)

    def test_apply_evidence_approval_and_exclusive_lock(self):
        with self.assertRaisesRegex(RuntimeError, 'evidence'):
            prep.apply_plan(self.api, self.root, self.services, self.reviewed, 'groups-only', None, '')
        with self.assertRaisesRegex(RuntimeError, 'Approval'):
            self.apply(approval='not-approved')
        path = self.root / 'evidence.json'
        path.write_text(json.dumps(self.evidence)); path.chmod(0o600)
        self.assertEqual(prep.evidence_input(path), self.evidence)
        for field in ('writers_paused', 'backup_sha256', 'restore_test_sha256', 'reviewed_tool_sha256'):
            evidence = dict(self.evidence, **{field: False if field == 'writers_paused' else 'invalid'})
            path.write_text(json.dumps(evidence))
            with self.assertRaises(RuntimeError):
                prep.evidence_input(path)
        with prep.locked(self.root):
            with self.assertRaisesRegex(RuntimeError, 'holds the lock'):
                with prep.locked(self.root):
                    self.fail('second lock acquired')
        self.assertEqual(self.api.writes, 0)

    def test_cli_default_plan_and_check_are_get_only_no_journal(self):
        (self.root / 'services.json').write_text(json.dumps(self.services))
        (self.root / 'account-mappings.json').write_text(json.dumps(self.reviewed))
        for action, status in [([], 0), (['check'], 1)]:
            with patch.object(sys, 'argv', ['prepare_app_iam.py', str(self.root), *action]), \
                    patch.object(prep, 'api_for', return_value=self.api), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(prep.main(), status)
        self.assertEqual(self.api.writes, 0)
        self.assertFalse((self.root / 'app-iam-prepare-journal').exists())
        self.assertEqual({p.name for p in self.root.iterdir()},
                         {'services.json', 'account-mappings.json', '.app-iam-prepare.lock'})


if __name__ == '__main__':
    unittest.main()
