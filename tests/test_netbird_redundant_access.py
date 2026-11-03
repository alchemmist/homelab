import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'scripts'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mesh = load('netbird-redundant-access')
relay = load('netbird-independent-relay')
dns = load('netbird-macos-bootstrap-dns')
base = load('netbird-host-peer')


class IndependentAccessTest(unittest.TestCase):
    def test_four_exact_hosts_opt_in_no_implicit_enrollment(self):
        docs = mesh.manifests()
        self.assertEqual(len(docs), 8)
        for host in mesh.HOSTS:
            pvc, deploy = mesh.peer(host)
            self.assertEqual(deploy['spec']['replicas'], 0)
            spec = deploy['spec']['template']['spec']
            self.assertEqual(spec['nodeSelector'], {'kubernetes.io/hostname': host})
            self.assertTrue(spec['hostNetwork'])
            env = {e['name']: e.get('value') for e in spec['containers'][0]['env']}
            self.assertEqual(env['NB_DISABLE_SERVER_ROUTES'], 'false')
            self.assertEqual(env['NB_DISABLE_CLIENT_ROUTES'], 'true')
            self.assertEqual(env['NB_DISABLE_DNS'], 'true')
            self.assertIn('@sha256:', spec['containers'][0]['image'])
        with self.assertRaises(ValueError):
            base.peer('socrat-1')
        with self.assertRaises(ValueError):
            mesh.peer('new-vm')

    def test_native_group_router_not_single_peer_or_default_route(self):
        self.assertEqual(mesh.router_body('exact-node-group'), {
            'peer_groups': ['exact-node-group'], 'enabled': True, 'masquerade': True, 'metric': 80})
        self.assertEqual(set(mesh.NODE_ADDRESSES.values()), {
            '10.250.0.1/32', '10.250.0.2/32', '10.250.0.3/32', '10.250.0.5/32'})
        for bad in [None, '', 'All', 'default', [], 'group/other', 'group name']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mesh.router_body(bad)

    def test_distinct_input_policies_keep_pilot_tcp_only(self):
        admin = mesh.admin_input_policy('jwt-admin', 'nodes')['rules'][0]
        pilot = mesh.pilot_input_policy('jwt-pilot', 'only-node2')['rules'][0]
        self.assertEqual(admin['sources'], ['jwt-admin'])
        self.assertEqual(admin['destinations'], ['nodes'])
        self.assertFalse(admin['bidirectional'])
        self.assertEqual(admin['protocol'], 'all')
        self.assertEqual(pilot['sources'], ['jwt-pilot'])
        self.assertEqual(pilot['destinations'], ['only-node2'])
        self.assertEqual(pilot['protocol'], 'tcp')
        self.assertEqual(pilot['ports'], ['2222'])
        for fn in [mesh.admin_input_policy, mesh.pilot_input_policy]:
            for args in [('same', 'same'), ('All', 'nodes'), ('jwt', 'default'), ([], 'nodes')]:
                with self.assertRaises(ValueError):
                    fn(*args)

    def test_relay_pinned_vps_and_no_secret_values_or_management(self):
        docs = relay.manifests()
        self.assertEqual([d['kind'] for d in docs], ['Deployment', 'Service', 'NetworkPolicy', 'Certificate', 'Ingress'])
        pod = docs[0]['spec']['template']['spec']
        self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname': 'socrat-2'})
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertNotIn('hostNetwork', pod)
        container = pod['containers'][0]
        self.assertIn('@sha256:', container['image'])
        self.assertEqual(container['resources']['limits']['memory'], '64Mi')
        self.assertEqual(container['readinessProbe']['httpGet'], {'path': '/health', 'port': 9000})
        env = {e['name']: e for e in container['env']}
        self.assertEqual(env['NB_ENABLE_STUN']['value'], 'false')
        self.assertNotIn('value', env['NB_AUTH_SECRET'])
        self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
        self.assertEqual(container['securityContext']['capabilities']['drop'], ['ALL'])
        ingress = docs[-1]['spec']
        self.assertEqual(ingress['rules'][0]['http']['paths'][0]['path'], '/relay')
        self.assertEqual(ingress['rules'][0]['http']['paths'][0]['pathType'], 'Exact')
        self.assertNotIn('/api', yaml.safe_dump(docs))

    def test_native_self_health_bootstrap_and_actual_vps_cni(self):
        service, policy = relay.manifests()[1:3]
        self.assertTrue(service['spec']['publishNotReadyAddresses'])
        self.assertEqual(service['metadata']['annotations']['traefik.ingress.kubernetes.io/service.nativelb'], 'true')
        ingress = policy['spec']['ingress'][0]
        cidrs = {source['ipBlock']['cidr'] for source in ingress['from']}
        self.assertIn('10.42.0.1/32', cidrs)
        self.assertNotIn('10.42.2.1/32', cidrs)
        self.assertNotIn('0.0.0.0/0', cidrs)
        self.assertEqual(ingress['ports'], [{'protocol': 'TCP', 'port': 33080}])

    def test_home_relay_is_separate_and_reuses_existing_tls(self):
        deploy, service, policy, ingress = relay.home_manifests()
        self.assertEqual(deploy['spec']['template']['spec']['nodeSelector'], {'kubernetes.io/hostname': 'socrat-0'})
        self.assertEqual(service['spec']['selector'], {'app': 'netbird-relay-home'})
        self.assertTrue(service['spec']['publishNotReadyAddresses'])
        self.assertEqual(ingress['spec']['tls'][0]['secretName'], 'netbird-pilot-tls')
        self.assertEqual(ingress['spec']['rules'][0]['host'], 'netbird.socrat.alchemmist.xyz')
        sources = policy['spec']['ingress'][0]['from']
        self.assertEqual(sources[0]['podSelector']['matchLabels'], {'app.kubernetes.io/name': 'traefik'})
        self.assertEqual(sources[0]['namespaceSelector']['matchLabels'], {'kubernetes.io/metadata.name': 'kube-system'})
        self.assertEqual(relay.advertised_relays()['addresses'], [relay.URI, relay.HOME_URI])
        self.assertEqual(relay.advertised_relays()['credentialsTTL'], '12h')
        self.assertNotIn('relay', relay.advertised_relays())

    def test_mac_bootstrap_does_not_depend_on_internal_dns(self):
        self.assertEqual(len(dns.HOSTS), 3)
        self.assertIn('auth.socrat.alchemmist.xyz', dns.HOSTS)
        body = dns.render().decode()
        self.assertNotIn('10.250.', body)
        self.assertIn('nameserver 1.1.1.1\n', body)
        self.assertIn('nameserver 9.9.9.9\n', body)
        self.assertNotIn('socrat.alchemmist.xyz', body)  # no broad resolver rewrite


if __name__ == '__main__':
    unittest.main()
