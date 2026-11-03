import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

net = load('internal_net', 'scripts/netbird-internal-network.py')
owner = load('owner_guard', 'scripts/netbird-owner-handover.py')
oidc = load('net_oidc', 'ansible/roles/identity_integrations/files/netbird_oidc.py')


class InternalNetworkTests(unittest.TestCase):
    def test_single_gateway_exact_resources_and_separate_local_input_gate(self):
        expected = {'10.250.0.1/32', '10.250.0.2/32', '10.250.0.3/32', '10.250.0.5/32'}
        actual = {a for _, addresses in net.NETWORKS.values() for a in addresses}
        self.assertEqual(actual, expected)
        self.assertEqual(set(net.NETWORKS), {'socrat-0'})
        with self.assertRaises(ValueError):
            net.resource_body('socrat-0', '10.250.0.1/32')
        self.assertEqual(net.resource_body('socrat-0', '10.250.0.1/32',
                                          local_input_authorized=True)['name'], 'wg-socrat-0')
        with self.assertRaises(ValueError):
            net.resource_body('socrat-2', '10.250.0.2/32')
        rule = net.gateway_input_policy('real-admin-jwt', 'exact-gateway-api')['rules'][0]
        self.assertEqual(rule['sources'], ['real-admin-jwt'])
        self.assertEqual(rule['destinations'], ['exact-gateway-api'])
        self.assertFalse(rule['bidirectional'])
        self.assertNotIn('destinationResource', rule)
        for address in ['0.0.0.0/0', '10.250.0.0/24', '10.42.0.0/16', '192.168.0.0/24']:
            with self.assertRaises(ValueError):
                net.resource_body('socrat-0', address)

    def test_clients_do_not_import_routes_but_serve_explicit_networks(self):
        docs = net.peers()
        self.assertEqual([o['metadata']['name'] for o in docs if o['kind'] == 'Deployment'],
                         ['machine-socrat-0'])
        for obj in docs:
            if obj['kind'] != 'Deployment':
                continue
            self.assertEqual(obj['spec']['replicas'], 0)
            pod = obj['spec']['template']['spec']
            self.assertTrue(pod['hostNetwork'])
            self.assertFalse(pod['automountServiceAccountToken'])
            container = pod['containers'][0]
            self.assertEqual(container['resources']['limits']['memory'], '96Mi')
            env = {e['name']: e.get('value') for e in container['env']}
            for flag in ['NB_DISABLE_CLIENT_ROUTES', 'NB_DISABLE_DNS']:
                self.assertEqual(env[flag], 'true')
            self.assertEqual(env['NB_DISABLE_SERVER_ROUTES'], 'false')
            self.assertEqual(env['NB_ALLOW_SERVER_SSH'], 'false')
        self.assertTrue(net.router_body('exact-peer')['masquerade'])

    def test_fake_api_admin_group_or_observer_group_never_accepted(self):
        for groups in [[], [{'name': net.ADMIN_GROUP, 'issued': 'api', 'id': 'fake'}],
                       [{'name': 'netbird-pilot-login', 'issued': 'jwt', 'id': 'observer'}]]:
            with self.assertRaises(ValueError):
                net.genuine_admin_group(groups)
        self.assertEqual(net.genuine_admin_group([{'name': net.ADMIN_GROUP, 'issued': 'jwt', 'id': 'real'}]), 'real')
        rule = net.policy_body('real', 'resource')['rules'][0]
        self.assertEqual(rule['sources'], ['real'])
        self.assertEqual(rule['destinationResource'], {'id': 'resource', 'type': 'host'})
        self.assertFalse(rule['bidirectional'])
        self.assertNotIn('All', str(rule))

    def test_admin_claim_not_part_of_automatic_pilot_human_grants(self):
        self.assertNotIn(net.ADMIN_GROUP, oidc.GROUP_NAMES)
        self.assertIn(net.ADMIN_GROUP, oidc.PROFILE_GROUP_NAMES)
        self.assertIn(net.ADMIN_GROUP, oidc.profile_expression())

    def test_owner_handover_accepts_only_one_exact_owner_device_explicitly(self):
        p = {'id': 'mac', 'user_id': owner.subject(), 'approval_required': False, 'login_expired': False}
        def api(peers, policies=None):
            return lambda endpoint: peers if endpoint == 'peers' else (policies or []) if endpoint == 'policies' else []
        with self.assertRaises(ValueError):
            owner.network_snapshot(api([p]))
        self.assertEqual(owner.network_snapshot(api([p]), True)[0]['id'], 'mac')
        for peers in [[p, p], [dict(p, user_id='someone-else')],
                      [dict(p, approval_required=True)], [dict(p, login_expired=True)]]:
            with self.assertRaises(ValueError):
                owner.network_snapshot(api(peers), True)
        with self.assertRaises(ValueError):
            owner.network_snapshot(api([p], ['unexpected-policy']), True)
