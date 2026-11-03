"""Control-plane deploy, bootstrap, and backup guards. Not a live acceptance test."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nb = load('netbird_pilot', 'netbird-pilot.py')
deploy = load('netbird_deploy', 'netbird-deploy.py')
bootstrap = load('netbird_bootstrap', 'netbird-bootstrap.py')
backup = load('netbird_backup', 'netbird-backup.py')


def control_inputs():
    review = {key: False for key in nb.REVIEWS}
    for key in nb.CONTROL_REVIEWS:
        review[key] = True
    return {'schema_version': 1, 'management_fqdn': 'netbird.socrat.alchemmist.xyz',
            'management_node': 'test-node', 'tls_secret_name': 'test-tls', 'ingress_class': 'traefik',
            'stun_node_port': 31478, 'storage_class': 'local-path', 'review': review}


def cleared_audit():
    audit = json.loads((ROOT / 'deploy/netbird/runtime-audit.json').read_text())
    audit.update(kubectl_api_read=True, udp_3478_listening=False, traefik_watches_netbird_edge=True,
                 traefik_watches_netbird_pilot=False, port_forward_cidrs=['203.0.113.10/32'])
    return audit


class ControlPlaneTests(unittest.TestCase):
    def test_repo_check_reports_concrete_blockers_without_applying(self):
        result = subprocess.run([os.sys.executable, str(ROOT / 'scripts/netbird-deploy.py'), 'check'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('BLOCKED', result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['apply_allowed'])
        self.assertFalse(report['network_grant_allowed'])
        self.assertFalse(report['management_ha'])
        self.assertEqual(report['approved_fqdn'], 'netbird.socrat.alchemmist.xyz')
        self.assertEqual(report['pilot_users'], ['owner', 'tim'])
        self.assertFalse(report['scope']['netbird_edge_watched'])
        self.assertFalse(report['scope']['netbird_pilot_watched'])
        self.assertEqual(report['scope']['crd_namespaces'], ['argocd'])
        blockers = '\n'.join(report['apply_blockers'] + report['network_blockers'])
        self.assertNotIn('is not listening', blockers)
        self.assertFalse(report['udp_3478_preexisting'])
        self.assertFalse(report['udp_3478_required_before_internal_apply'])
        self.assertFalse(report['internal_apply_allowed'])
        self.assertFalse(report['edge_apply_allowed'])
        self.assertIn('netbird-edge', blockers)
        self.assertIn('password', blockers)
        self.assertIn('shared private web frontend', blockers)
        self.assertIn('10.250.0.2', blockers)
        self.assertIn('unresolved', blockers)
        self.assertIn('existing-node', blockers.lower())
        self.assertIn('groups claim', blockers)
        self.assertIn('/api/setup', blockers)

    def test_chart_candidate_is_not_marked_verified(self):
        chart = yaml.safe_load((ROOT / 'charts/traefik-edge/values.yaml').read_text())
        candidates = json.loads((ROOT / 'deploy/netbird/candidates.json').read_text())
        self.assertNotIn('netbird-edge', chart['watchNamespaces'])
        self.assertNotIn('netbird-pilot', chart['watchNamespaces'])
        self.assertEqual(chart['kubernetesCRD']['namespaces'], ['argocd'])
        self.assertFalse(chart['kubernetesCRD'].get('allowCrossNamespace', False))
        self.assertFalse(candidates['ingress_class']['verified'])
        self.assertFalse(candidates['storage_class']['verified'])
        self.assertFalse(candidates['management_fqdn']['dns_tls_verified'])
        self.assertFalse(candidates['authentik_oidc']['groups_claim_verified'])
        self.assertEqual(candidates['routers']['mode'], 'existing-node')
        self.assertFalse(candidates['routers']['existing_node_router_mode_reviewed'])
        self.assertFalse(candidates['routers']['placement_resolved'])
        self.assertFalse(candidates['routers']['new_machines_approved'])
        self.assertEqual(candidates['ingress_class']['value'], 'traefik')
        self.assertEqual(candidates['storage_class']['value'], 'local-path')
        self.assertEqual(nb.image('edge_forwarder'), chart['image'])
        self.assertFalse((ROOT / 'deploy/argocd/apps').joinpath('netbird.yaml').exists())

    def test_control_plane_does_not_require_routers_or_grant_resources(self):
        inputs = control_inputs()
        nb.validate_control_plane(inputs)
        with self.assertRaises(ValueError):
            nb.validate(inputs)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'rendered'
            nb.render_control_plane(inputs, out, ['203.0.113.10/32'])
            self.assertEqual(sorted(path.name for path in out.iterdir()), ['management.yaml'])
            docs = list(yaml.safe_load_all((out / 'management.yaml').read_text()))
            deploy.assert_safe_manifests(docs)
            text = (out / 'management.yaml').read_text()
            self.assertNotIn('routing-peer', text)
            self.assertNotIn('192.168.88.10', text)
            self.assertNotIn('kind: Secret', text)
            self.assertNotIn('kind: Service', text)
            self.assertNotIn('kind: Ingress', text)
            self.assertIn('/oauth2/.well-known/openid-configuration', text)

    def test_cleared_audit_cannot_hide_the_unpatched_chart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / 'inputs.json'
            audit = root / 'audit.json'
            out = root / 'out'
            inputs.write_text(json.dumps(control_inputs()))
            audit.write_text(json.dumps(cleared_audit()))
            result = subprocess.run([os.sys.executable, str(ROOT / 'scripts/netbird-deploy.py'), 'plan',
                                     '--inputs', str(inputs), '--audit', str(audit), '--out', str(out)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('BLOCKED', result.stderr)
            self.assertFalse(out.exists())

    def test_internal_stage_does_not_wait_for_edge_or_a_listening_udp_port(self):
        audit = cleared_audit()
        audit.update(traefik_watches_netbird_edge=False, udp_3478_listening=False,
                     port_forward_cidrs=['203.0.113.10/32', '10.42.0.1/32'])
        chart = yaml.safe_load((ROOT / 'charts/traefik-edge/values.yaml').read_text())
        candidates = json.loads((ROOT / 'deploy/netbird/candidates.json').read_text())
        delta = json.loads((ROOT / 'deploy/netbird/traefik-scope-delta.json').read_text())
        status = deploy.report(control_inputs(), candidates, audit, chart, delta)
        self.assertTrue(status['internal_apply_allowed'])
        self.assertFalse(status['edge_apply_allowed'])
        self.assertFalse(status['udp_3478_preexisting'])
        self.assertFalse(any('is not listening' in item for item in status['apply_blockers']))
        audit['udp_3478_listening'] = True
        blocked = deploy.report(control_inputs(), candidates, audit, chart, delta)
        self.assertTrue(blocked['internal_apply_allowed'])
        self.assertFalse(blocked['edge_apply_allowed'])
        self.assertTrue(any('preexisting listener' in item for item in blocked['edge_blockers']))

    def test_in_memory_scope_can_clear_only_after_the_watch_exists(self):
        chart = yaml.safe_load((ROOT / 'charts/traefik-edge/values.yaml').read_text())
        candidates = json.loads((ROOT / 'deploy/netbird/candidates.json').read_text())
        delta = json.loads((ROOT / 'deploy/netbird/traefik-scope-delta.json').read_text())
        blocked = deploy.report(control_inputs(), candidates, cleared_audit(), chart, delta)
        self.assertFalse(blocked['apply_allowed'])
        chart['watchNamespaces'] = list(chart['watchNamespaces']) + ['netbird-edge']
        ready = deploy.report(control_inputs(), candidates, cleared_audit(), chart, delta)
        self.assertTrue(ready['apply_allowed'])
        self.assertFalse(ready['network_grant_allowed'])
        self.assertFalse((ROOT / 'charts/traefik-edge/values.yaml').read_text().count('netbird-edge'))

    def test_apply_argv_is_explicit_and_rejects_default_context(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'rendered'
            nb.render_control_plane(control_inputs(), out, ['203.0.113.10/32'])
            manifest = out / 'management.yaml'
            argv = deploy.apply_argv(manifest, 'lab')
            self.assertEqual(argv[:4], ['kubectl', '--context', 'lab', 'apply'])
            self.assertNotIn('argocd', argv)
            with self.assertRaises(ValueError):
                deploy.apply_argv(manifest, 'default')

    def test_auth_modes_match_upstream_startup_rules(self):
        secrets = {'NB_RELAY_SECRET': 'relay-secret-' * 3, 'NB_COOKIE_KEY': 'cookie', 'NB_STORE_KEY': 'store'}
        bootstrap_config = nb.server_config(control_inputs(), secrets, 'bootstrap')
        auth = bootstrap_config['server']['auth']
        self.assertFalse(auth['localAuthDisabled'])
        self.assertNotIn('owner', auth)
        self.assertEqual(bootstrap_config['server']['stunPorts'], [3478])
        self.assertEqual(bootstrap_config['server']['authStore']['file'], 'idp.db')
        self.assertEqual(bootstrap_config['server']['listenAddress'], ':80')
        with tempfile.TemporaryDirectory() as directory:
            witness = Path(directory) / 'witness.json'
            witness.write_text(json.dumps({'external_connectors': 0}))
            with self.assertRaises(ValueError):
                nb.witness_ready(witness)
            witness.write_text(json.dumps({'external_connectors': 1, 'client_secret': 'nope'}))
            with self.assertRaises(ValueError):
                nb.witness_ready(witness)
            witness.write_text(json.dumps({'external_connectors': 1}))
            nb.witness_ready(witness)
            disabled = nb.server_config(control_inputs(), secrets, 'idp-only')
            self.assertTrue(disabled['server']['auth']['localAuthDisabled'])
            self.assertNotIn('owner', disabled['server']['auth'])

    def test_idp_only_cli_refuses_missing_witness_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'inputs.json'
            target = Path(directory) / 'config.yaml'
            source.write_text(json.dumps(control_inputs() | {
                'overlay_cidr': '100.100.0.0/24',
                'authentik_issuer': 'https://auth.socrat.alchemmist.xyz/application/o/netbird-pilot/',
                'oidc_client_id': 'pilot', 'login_group': 'pilot-login', 'routing_peers': [],
                'resources': [], 'review': {key: True for key in nb.REVIEWS}}))
            # Full validate is required by runtime-config; the dict above is incomplete for peers.
            # Use the synthetic access fixture shape from the pilot tests via a local complete object.
            from test_netbird_pilot import inputs
            source.write_text(json.dumps(inputs()))
            env = {**os.environ, 'NB_RELAY_SECRET': 'relay-secret-' * 3,
                   'NB_COOKIE_KEY': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',  # replaced below
                   'NB_STORE_KEY': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'}
            import base64
            env['NB_COOKIE_KEY'] = base64.b64encode(b'a' * 32).decode()
            env['NB_STORE_KEY'] = base64.b64encode(b'b' * 32).decode()
            result = subprocess.run([os.sys.executable, str(ROOT / 'scripts/netbird-pilot.py'), 'runtime-config',
                                     '--auth-mode', 'idp-only', '--inputs', str(source), '--out', str(target)],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(target.exists())
            self.assertNotIn(env['NB_STORE_KEY'], result.stdout + result.stderr)


class BootstrapTests(unittest.TestCase):
    def test_public_origin_and_pat_are_refused(self):
        for origin in ['https://netbird.socrat.alchemmist.xyz', 'http://netbird.socrat.alchemmist.xyz',
                       'http://10.250.0.2:80', 'http://127.0.0.1:8080/api/setup']:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                bootstrap.assert_loopback(origin)
        body = bootstrap.setup_body('owner@example.com', 'long-enough', 'Owner')
        self.assertEqual(set(body), {'email', 'password', 'name'})
        self.assertNotIn('create_pat', body)

    def test_claim_redacts_token_and_requires_setup(self):
        calls = []

        def opener(url, body):
            calls.append((url, body))
            if url.endswith('/api/instance'):
                return {'setup_required': True}
            return {'user_id': 'user123', 'email': 'owner@example.com',
                    'personal_access_token': 'nbp_secret_token'}

        result = bootstrap.claim('http://127.0.0.1:18080', 'owner@example.com', 'long-enough', 'Owner', opener)
        self.assertEqual(result['user_id'], 'user123')
        self.assertTrue(result['personal_access_token_redacted'])
        self.assertNotIn('nbp_secret_token', json.dumps(result))
        self.assertNotIn('long-enough', json.dumps(result))
        self.assertIsNone(calls[1][1].get('create_pat') if False else calls[1][1].get('create_pat', None))
        self.assertNotIn('create_pat', calls[1][1])

        def claimed(url, body):
            return {'setup_required': False}

        with self.assertRaises(ValueError):
            bootstrap.claim('http://127.0.0.1:18080', 'owner@example.com', 'long-enough', 'Owner', claimed)

    @unittest.skipUnless((Path('/tmp/netbird-v082-repo/shared/management/http/api/openapi.yml')).is_file(),
                         'pinned schema not present')
    def test_setup_body_matches_pinned_openapi(self):
        import hashlib
        path = Path('/tmp/netbird-v082-repo/shared/management/http/api/openapi.yml')
        lock = json.loads((ROOT / 'deploy/netbird/upstream.lock.json').read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), lock['sources']['openapi']['sha256'])
        schema = yaml.safe_load(path.read_text())
        required = schema['components']['schemas']['SetupRequest']['required']
        body = bootstrap.setup_body('owner@example.com', 'long-enough', 'Owner')
        self.assertEqual(required, ['email', 'password', 'name'])
        self.assertEqual(set(body), set(required))

    @unittest.skipUnless(
        Path('/tmp/netbird-0.82.0/shared/management/http/api/openapi.yml').is_file()
        and Path('/tmp/netbird-v082-repo/management/server/user.go').is_file(),
        'pinned source not present')
    def test_native_owner_transfer_updates_an_existing_subject(self):
        """PUT /api/users/{userId} can move owner to an existing subject. It does not rewrite user IDs."""
        import hashlib
        source = Path('/tmp/netbird-v082-repo/management/server/user.go').read_text().splitlines()
        self.assertIn(
            'initiatorUser.Role == types.UserRoleOwner && initiatorUser.Id != update.Id && update.Role == types.UserRoleOwner',
            source[914])
        self.assertIn(
            'initiatorUser.Role != types.UserRoleOwner && oldUser.Role == types.UserRoleOwner && update.Role != oldUser.Role',
            source[969])
        joined = '\n'.join(source)
        self.assertIn('return am.SaveOrAddUser(ctx, accountID, initiatorUserID, update, false)', joined)
        self.assertIn('updatedUser := oldUser.Copy()', joined)
        self.assertIn('updatedUser.Role = update.Role', joined)
        self.assertNotIn('updatedUser.Id = update.Id', joined)
        self.assertIn('func (am *DefaultAccountManager) GetOrCreateAccountByUser', joined)
        schema_path = Path('/tmp/netbird-0.82.0/shared/management/http/api/openapi.yml')
        lock = json.loads((ROOT / 'deploy/netbird/upstream.lock.json').read_text())
        self.assertEqual(hashlib.sha256(schema_path.read_bytes()).hexdigest(), lock['sources']['openapi']['sha256'])
        schema = yaml.safe_load(schema_path.read_text())
        operation = schema['paths']['/api/users/{userId}']['put']
        self.assertEqual(operation['requestBody']['content']['application/json']['schema']['$ref'],
                         '#/components/schemas/UserRequest')
        user_request = schema['components']['schemas']['UserRequest']
        self.assertEqual(user_request['required'], ['role', 'auto_groups', 'is_blocked'])
        self.assertNotIn('id', user_request['properties'])
        # Personal owner first login creates the account. The Authentik subject must already
        # exist because SaveUser refuses addIfNotExists. This test does not perform that login.
        self.assertIn('false means do not create user', joined)


class BackupTests(unittest.TestCase):
    def test_plan_is_quiesced_readonly_and_does_not_call_kubectl(self):
        image = nb.image('server')
        body = backup.plan('test-node', image)
        self.assertTrue(body['quiesce_required'])
        self.assertFalse(body['management_ha'])
        self.assertTrue(body['pod']['spec']['containers'][0]['volumeMounts'][0]['readOnly'])
        self.assertNotIn('secret', json.dumps(body['pod']))
        self.assertNotIn('hostNetwork', json.dumps(body['pod']))
        real_run = subprocess.run
        with tempfile.TemporaryDirectory() as directory:
            # Direct module calls must not run kubectl; capture the launcher first
            # because backup.subprocess is the shared Python subprocess module.
            with patch.object(backup.subprocess, 'run', side_effect=AssertionError('kubectl called')):
                self.assertTrue(backup.plan('test-node', image)['quiesce_required'])
            out = Path(directory) / 'backup'
            result = real_run([os.sys.executable, str(ROOT / 'scripts/netbird-backup.py'), 'plan',
                               '--node', 'test-node', '--image', image, '--out', str(out)],
                              capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            pod = yaml.safe_load((out / 'sqlite-copy-pod.yaml').read_text())
            self.assertTrue(pod['spec']['containers'][0]['volumeMounts'][0]['readOnly'])
            refused = real_run([os.sys.executable, str(ROOT / 'scripts/netbird-backup.py'), 'execute',
                                '--node', 'test-node', '--image', image,
                                '--out', str(Path(directory) / 'second'), '--confirm', 'no'],
                               capture_output=True, text=True)
            self.assertEqual(refused.returncode, 2)



class AnsibleGuardTests(unittest.TestCase):
    def test_role_defaults_to_local_check_without_transport_changes(self):
        text = '\n'.join(path.read_text() for path in [
            ROOT / 'ansible/playbooks/netbird-control-plane.yml',
            ROOT / 'ansible/roles/netbird_control_plane/defaults/main.yml',
            ROOT / 'ansible/roles/netbird_control_plane/tasks/main.yml'])
        self.assertIn('become: false', text)
        self.assertIn('netbird_action: check', text)
        self.assertNotIn('become: true', text)
        self.assertNotIn('wg-quick', text)
        self.assertNotIn('argocd', text.lower())
        self.assertNotIn('site.yml', (ROOT / 'ansible/playbooks/site.yml').read_text())


if __name__ == '__main__':
    unittest.main()
