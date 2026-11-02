import importlib.util
from pathlib import Path
import struct
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


peer = load('netbird-host-peer')
stun = load('netbird-stun')
probe = load('netbird-stun-check')


class HostPeerTest(unittest.TestCase):
    def groups(self):
        return [{'id': str(i), 'name': n, 'issued': 'jwt', 'peers': [], 'resources': []}
                for i, n in enumerate(peer.SOURCES)]

    def test_live_gate_no_default_and_real_jwt_only(self):
        self.assertEqual(peer.preflight([], self.groups(), [], 600*1024), ['0', '1'])
        for policies, groups, peers, mem in [
                ([{'name': 'Default'}], self.groups(), [], 600*1024),
                ([], [], [], 600*1024),
                ([], [dict(g, issued='api') for g in self.groups()], [], 600*1024),
                ([], self.groups(), [{'id': 'unplanned'}], 600*1024),
                ([], self.groups(), [], 400*1024),
                ([], [dict(g, peers=['unplanned']) for g in self.groups()], [], 600*1024)]:
            with self.assertRaises(ValueError):
                peer.preflight(policies, groups, peers, mem)

    def test_machine_not_router_no_credentials_or_host_root(self):
        for host in peer.HOSTS:
            docs = peer.peer(host)
            deployment = docs[1]
            self.assertEqual(deployment['spec']['replicas'], 0)
            spec = deployment['spec']['template']['spec']
            container = spec['containers'][0]
            self.assertTrue(spec['hostNetwork'])
            self.assertFalse(spec['automountServiceAccountToken'])
            self.assertNotIn('hostPID', spec)
            self.assertNotIn('privileged', container['securityContext'])
            self.assertEqual(container['securityContext']['capabilities']['add'], ['NET_ADMIN', 'NET_RAW', 'BPF'])
            self.assertEqual([v['hostPath']['path'] for v in spec['volumes'] if 'hostPath' in v], ['/dev/net/tun'])
            env = {e['name']: e for e in container['env']}
            for name in ['NB_DISABLE_CLIENT_ROUTES', 'NB_DISABLE_SERVER_ROUTES', 'NB_DISABLE_DNS']:
                self.assertEqual(env[name]['value'], 'true')
            self.assertEqual(env['NB_DISABLE_FIREWALL']['value'], 'false')
            self.assertNotIn('value', env['NB_SETUP_KEY'])
            self.assertIn('@sha256:', container['image'])
            self.assertEqual(container['resources']['limits']['memory'], '96Mi')
            blob = yaml.safe_dump(docs)
            for forbidden in ['wg-socrat', '/etc/wireguard', '/etc/ssh', 'docker.sock', '10.250.0.2/32', 'iptables -F']:
                self.assertNotIn(forbidden, blob)

    def test_single_use_native_key_body(self):
        for host in peer.HOSTS:
            key = peer.setup_key_body(host)
            self.assertEqual(key['type'], 'one-off')
            self.assertEqual(key['auto_groups'], [])
            self.assertEqual(key['usage_limit'], 1)
            self.assertLessEqual(key['expires_in'], 600)
        with self.assertRaises(ValueError):
            peer.setup_key_body('new-vm')

    def test_only_directed_tcp_ports_dedicated_groups(self):
        bodies = peer.policies(['jwt-grafana', 'jwt-ssh'], ['machine-grafana', 'machine-ssh'])
        for body, port in zip(bodies, ['8443', '2222']):
            rule = body['rules'][0]
            self.assertEqual(rule['protocol'], 'tcp')
            self.assertEqual(rule['ports'], [port])
            self.assertFalse(rule['bidirectional'])
            self.assertNotIn('All', str(rule))
        with self.assertRaises(ValueError):
            peer.policies(['same', 'same'], ['d1', 'd2'])

    def test_overlay_only_tls_host_sni_verified_upstream(self):
        cfg = peer.frontend_config('100.96.1.2')
        static = yaml.safe_load(cfg['static.yaml'])
        dynamic = yaml.safe_load(cfg['dynamic.yaml'])
        self.assertEqual(static['entryPoints']['grafana']['address'], '100.96.1.2:8443')
        self.assertNotIn('api', static)
        self.assertTrue(dynamic['tls']['options']['strict']['sniStrict'])
        http = dynamic['http']
        self.assertEqual(http['routers']['grafana']['rule'], 'Host(`grafana.socrat.alchemmist.xyz`)')
        self.assertEqual(http['middlewares']['fixed-upstream-host']['headers']['customRequestHeaders']['Host'], peer.GRAFANA)
        self.assertFalse(http['serversTransports']['verified']['insecureSkipVerify'])
        self.assertEqual(http['serversTransports']['verified']['serverName'], peer.GRAFANA)
        self.assertEqual(http['services']['grafana']['loadBalancer']['servers'], [{'url': 'https://10.250.0.3:443'}])
        for address in ['0.0.0.0', '176.98.185.59', '10.250.0.2', '100.96.1.2;evil']:
            with self.assertRaises(ValueError):
                peer.frontend_config(address)
        deployment = peer.frontend('socrat-0', '100.96.1.2')[1]
        self.assertEqual(deployment['spec']['replicas'], 0)
        guard = peer.frontend_guard()
        self.assertIn('iifname != "nb-host" tcp dport 8443 counter drop', guard)
        for forbidden in ['2222', '51830', 'flush', 'forward', 'masquerade']:
            self.assertNotIn(forbidden, guard)


class StunTest(unittest.TestCase):
    def test_bounded_stun_only_no_service_snat(self):
        docs = stun.manifests()
        self.assertEqual(len(docs), 1)
        spec = docs[0]['spec']['template']['spec']
        c = spec['containers'][0]
        self.assertTrue(spec['hostNetwork'])
        self.assertEqual(spec['nodeSelector']['kubernetes.io/hostname'], 'socrat-2')
        self.assertEqual(c['resources']['limits'], {'memory': '32Mi', 'cpu': '100m'})
        for flag in ['--stun-only', '--no-tcp', '--no-tls', '--no-dtls', '--no-cli', '--listening-ip=176.98.185.59']:
            self.assertIn(flag, c['args'])
        self.assertNotIn('hostPath', yaml.safe_dump(spec))
        self.assertNotIn('privileged', yaml.safe_dump(spec))
        self.assertEqual(c['securityContext']['capabilities']['add'], ['NET_BIND_SERVICE'])
        self.assertIn('@sha256:', c['image'])

    def binding(self):
        packet = probe.request(1)
        port = 12345 ^ 0x2112
        addr = bytes(a ^ b for a, b in zip(bytes([109, 173, 40, 247]), struct.pack('!I', probe.COOKIE)))
        val = b'\x00\x01' + struct.pack('!H', port) + addr
        response = b'\x01\x01\x00\x0c' + packet[4:20] + b'\x00\x20\x00\x08' + val
        return packet, response

    def test_binding_exact_transaction_and_source(self):
        packet, response = self.binding()
        self.assertEqual(probe.parse_binding(packet, response), {'address': '109.173.40.247', 'port': 12345})
        for bad in [response[:-1], response[:8] + b'x'*12 + response[20:], b'\x01\x03' + response[2:], response + b'bad']:
            with self.assertRaises(ValueError):
                probe.parse_binding(packet, bad)


if __name__ == '__main__':
    unittest.main()
