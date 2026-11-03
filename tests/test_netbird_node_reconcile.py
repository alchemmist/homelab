import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('nodes', ROOT/'scripts/netbird-node-reconcile.py')
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)
IMAGE = 'netbirdio/netbird:0.82.0@sha256:'+'a'*64


def node(host):
    return {'metadata': {'uid': 'node-'+host, 'name': host},
            'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}


class Fake(n.Runtime):
    def __init__(self, apply=True, existing=True):
        self.apply = apply
        self.config = n.validate_config({'image': IMAGE, 'reserved_addresses': ['10.250.0.4', '10.250.0.6', '10.250.0.7', '10.250.0.8'], 'nodes': {'socrat-4': '10.250.0.9'}})
        self.state = {'nodes': {}}
        self.changed = False
        self.writes = []
        self.cluster_node = node('socrat-4')
        self.peer = {'id': 'peer4', 'ip': '100.100.1.4', 'hostname': 'socrat-4', 'name': 'machine-socrat-4',
                     'user_id': '', 'connected': True, 'approval_required': False, 'login_expired': False}
        self.group = {'id': 'nodes', 'issued': 'api', 'name': n.DEST, 'peers': []}
        self.admin = {'id': 'jwt', 'issued': 'jwt', 'name': n.ADMIN}
        self.resources = []
        self.policies = [{'enabled': True, 'name': 'admin-input', 'rules': [
            {'enabled': True, 'action': 'accept', 'protocol': 'all', 'bidirectional': False,
             'sources': [{'id': 'jwt'}], 'destinations': [{'id': 'nodes'}]}]}]
        self.pvc, self.dep = n.manifests('socrat-4', IMAGE)
        self.pvc['metadata']['uid'] = 'pvc4'
        self.dep['metadata']['uid'] = 'dep4'
        for obj in [self.dep, self.pvc]:obj['metadata']['labels'] = {'app.kubernetes.io/instance': 'netbird'}
        self.existing = existing
        self.enrolled = existing
        self.fail_restart = False

    def save(self):
        pass

    def api(self, method, path, body=None):
        if method == 'GET':
            if path == 'groups': return [self.admin, self.group, {'name': 'All', 'id': 'all', 'issued': 'api'}]
            if path == 'networks': return [{'id': 'net', 'name': n.NETWORK}]
            if path.endswith('/routers'): return [{'id': 'router', 'peer_groups': ['nodes'],
                'enabled': True, 'masquerade': True, 'metric': 80}]
            if path == 'policies': return copy.deepcopy(self.policies)
            if path == 'peers': return [self.peer] if self.enrolled else []
            if path == 'groups/nodes': return copy.deepcopy(self.group)
            if path.endswith('/resources'): return self.resources
        self.writes.append((method, path, copy.deepcopy(body)))
        if path == 'setup-keys': return {'id': 'one-use', 'key': 'fixture-not-a-real-secret'}
        if path == 'setup-keys/one-use': return {'revoked': True}
        if path == 'groups/nodes':
            self.group['peers'] = [{'id': p} for p in body['peers']]; return self.group
        if path.endswith('/resources'):
            result = dict(body, id='res', type='host'); self.resources.append(result); return result
        if path == 'policies':
            result = dict(copy.deepcopy(body), id='policy4')
            result['rules'][0]['sources'] = [{'id': p} for p in body['rules'][0]['sources']]
            self.policies.append(result); return result
        raise AssertionError(path)

    def get(self, kind, name, ns=n.NS, optional=False):
        if kind == 'application':return {'metadata': {'labels': {'app.kubernetes.io/instance': 'root'}},
            'spec': {'project': 'default', 'source': {'path': 'charts/netbird', 'targetRevision': 'main',
                     'repoURL': 'https://github.com/alchemmist/homelab.git'}}}
        if kind == 'namespace': return {'metadata': {'uid': name}}
        if kind == 'node': return self.cluster_node
        if kind == 'deployment': return copy.deepcopy(self.dep) if self.existing else None
        if kind == 'pvc': return copy.deepcopy(self.pvc) if self.existing else None
        if kind == 'secret': return {'metadata': {'name': name, 'uid': 'secret4', 'resourceVersion': '1'}}
        raise AssertionError(kind)

    def status(self, host):
        return {'ip': self.peer['ip'], 'key': 'fixture-public-key'}

    def restart_without_key(self, host, deployment):
        if self.fail_restart:raise ValueError('simulated restart failure')

    def kub(self, args, obj=None, optional=False, stdin=None):
        if stdin is not None:
            assert args[-4:] == ['netbird', 'up', '--setup-key-file', '/dev/stdin']
            self.enrolled = True
        if args[-3:] == ['netbird', 'status', '--json']:
            return json.dumps({'daemonStatus': 'Connected' if self.enrolled else 'NeedsLogin', 'netbirdIp': self.peer['ip'] if self.enrolled else ''}).encode()
        assert not any(a in args for a in ['create', 'apply', 'replace', 'patch']), 'controller must not deploy workloads'
        if 'address' in args:
            return json.dumps([{'addr_info': [{'local': '10.250.0.9'}]}]).encode()
        if args[:2] == ['get', 'nodes']:
            return json.dumps({'items': [self.cluster_node]}).encode()
        return b'{}'


class ReconcileTest(unittest.TestCase):
    def seed(self): return {'nodes': {'socrat-4': {'id': 'peer4'}}}

    def test_inventory_is_generic_but_not_arbitrary_network_access(self):
        for values in [{'socrat-4': '10.250.0.4'}, {'other': '10.250.0.9'}, {'socrat-4': '0.0.0.0/0'},
                       {'socrat-4': '10.250.0.9/32'}, {'socrat-4': '10.250.0.255'},
                       {'socrat-4': '10.250.0.9', 'socrat-5': '10.250.0.9'}]:
            with self.assertRaises(ValueError):n.validate_config({'image': IMAGE, 'reserved_addresses': ['10.250.0.4', '10.250.0.6', '10.250.0.7', '10.250.0.8'], 'nodes': values})
        with self.assertRaises(ValueError):n.validate_config({'image': 'latest', 'nodes': {'socrat-4': '10.250.0.9'}})

    def test_render_has_persistent_identity_and_no_human_or_dns_permissions(self):
        pvc, deploy = n.manifests('socrat-28', IMAGE)
        pod = deploy['spec']['template']['spec']
        env = {e['name']: e.get('value') for e in pod['containers'][0]['env']}
        self.assertNotIn('NB_SETUP_KEY', env)
        self.assertEqual(env['NB_DISABLE_DNS'], 'true')
        self.assertEqual(env['NB_DISABLE_CLIENT_ROUTES'], 'true')
        self.assertEqual(env['NB_DISABLE_SERVER_ROUTES'], 'false')
        self.assertEqual(env['NB_ALLOW_SERVER_SSH'], 'false')
        self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname': 'socrat-28'})
        self.assertFalse(pod['automountServiceAccountToken'])

    def test_adopt_requires_trusted_exact_peer_not_name(self):
        for seed in [None, {'nodes': {'socrat-4': {'id': 'wrong'}}}]:
            f = Fake()
            with self.assertRaises(ValueError):f.reconcile('socrat-4', seed)
            self.assertEqual(f.writes, [])

    def test_adopt_and_second_run_are_idempotent(self):
        f = Fake();self.assertTrue(f.reconcile('socrat-4', self.seed())['changed'])
        self.assertEqual(len(f.resources), 1)
        writes = len(f.writes); f.changed = False
        self.assertFalse(f.reconcile('socrat-4')['changed'])
        self.assertEqual(len(f.writes), writes)

    def test_plan_never_enrolls_or_writes(self):
        f = Fake(apply=False, existing=False)
        self.assertEqual(f.reconcile('socrat-4')['status'], 'awaiting-argocd-workloads')
        self.assertEqual(f.writes, [])

    def test_missing_git_workloads_are_deferred_without_kubernetes_or_api_writes(self):
        f = Fake(existing=False)
        self.assertEqual(f.reconcile('socrat-4')['status'], 'awaiting-argocd-workloads')
        self.assertEqual(f.writes, [])

    def test_fresh_argocd_agent_plan_has_no_setup_key(self):
        f = Fake(apply=False); f.enrolled = False
        self.assertEqual(f.reconcile('socrat-4')['status'], 'would-enroll-and-authorize')
        self.assertEqual(f.writes, [])

    def test_unmanaged_workloads_cannot_be_adopted_by_controller(self):
        f = Fake(); f.dep['metadata'].pop('labels')
        with self.assertRaises(ValueError):f.reconcile('socrat-4', self.seed())
        self.assertEqual(f.writes, [])

    def test_missing_not_ready_node_is_deferred(self):
        f = Fake(); f.cluster_node = None
        self.assertEqual(f.reconcile('socrat-4')['status'], 'deferred-node-not-ready')
        self.assertEqual(f.writes, [])

    def test_simulated_new_node_flow_retires_key_and_second_run_no_writes(self):
        f = Fake(); f.enrolled = False
        self.assertTrue(f.reconcile('socrat-4')['changed'])
        self.assertEqual(f.state['cleanup']['revoked'], True)
        self.assertEqual(f.state['nodes']['socrat-4']['phase'], 'ready')
        self.assertFalse(any(e['name'] == 'NB_SETUP_KEY' for e in f.dep['spec']['template']['spec']['containers'][0]['env']))
        writes = len(f.writes); f.changed = False
        self.assertFalse(f.reconcile('socrat-4')['changed'])
        self.assertEqual(len(f.writes), writes)

    def test_failed_enrollment_revokes_known_key_and_never_auto_reissues(self):
        f = Fake(); f.enrolled = False; f.fail_restart = True
        with self.assertRaises(ValueError):f.reconcile('socrat-4')
        self.assertTrue(f.state['cleanup']['revoked'])
        self.assertNotEqual(f.state['nodes']['socrat-4']['phase'], 'ready')
        writes = len(f.writes)
        with self.assertRaises(ValueError):f.reconcile('socrat-4')
        self.assertEqual(len(f.writes), writes)

    def test_node_uid_pvc_peer_address_and_image_drift_are_not_repaired(self):
        for kind in ['node', 'pvc', 'peer', 'address', 'image', 'key', 'deleted-volume']:
            f = Fake(); f.reconcile('socrat-4', self.seed()); before = len(f.writes)
            if kind == 'node':f.cluster_node['metadata']['uid'] = 'replacement'
            if kind == 'pvc':f.pvc['metadata']['uid'] = 'replacement'
            if kind == 'peer':f.peer['id'] = 'replacement'
            if kind == 'address':f.config['nodes']['socrat-4'] = '10.250.0.10'
            if kind == 'image':f.dep['spec']['template']['spec']['containers'][0]['image'] = 'latest'
            if kind == 'key':f.state['nodes']['socrat-4']['public_key'] = 'different'
            if kind == 'deleted-volume':f.existing = False;f.enrolled = False
            with self.subTest(kind=kind),self.assertRaises(ValueError):f.reconcile('socrat-4')
            self.assertEqual(len(f.writes), before)

    def test_fake_jwt_broad_acl_or_wrong_router_fail_before_writes(self):
        for kind in ['jwt', 'input', 'member']:
            f = Fake()
            if kind == 'jwt':f.admin['issued'] = 'api'
            if kind == 'input':f.policies[0]['rules'][0]['sources'] = [{'id': 'All'}]
            if kind == 'member':f.group['peers'] = [{'id': 'human-device'}]
            with self.assertRaises(ValueError):f.reconcile('socrat-4', self.seed())
            self.assertEqual(f.writes, [])

    def test_removed_or_broadened_grants_are_not_resurrected(self):
        for kind in ['resource', 'policy', 'disabled', 'broadened', 'membership']:
            f = Fake(); f.reconcile('socrat-4', self.seed()); before = len(f.writes)
            if kind == 'membership':f.group['peers'] = []
            if kind == 'resource':f.resources = []
            if kind == 'policy':f.policies = f.policies[:1]
            if kind == 'disabled':f.policies[-1]['enabled'] = False
            if kind == 'broadened':f.policies[-1]['rules'][0]['sources'] = [{'id': 'All'}]
            with self.subTest(kind=kind),self.assertRaises(ValueError):f.reconcile('socrat-4')
            self.assertEqual(len(f.writes), before)

    def test_uncertain_write_remains_blocking(self):
        f = Fake();f.state['pending'] = {'method': 'POST', 'path': 'policies'}
        with self.assertRaises(ValueError):f.write('POST', 'policies', {})
        self.assertEqual(f.writes, [])
