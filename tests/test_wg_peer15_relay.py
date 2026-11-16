import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('peer15_endpoint', ROOT / 'scripts/wg-peer15-endpoint.py')
endpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(endpoint)


class EndpointTests(unittest.TestCase):
    def config(self):
        return ('[Interface]\nPrivateKey = SYNTHETIC-NOT-A-KEY\nListenPort = 51830\n\n'
                '[Peer]\nPublicKey = other-peer\nEndpoint = 127.0.0.1:51840\n\n'
                '[Peer]\n# socrat-1\nPublicKey = '+endpoint.PEER+'\n'
                'AllowedIPs = 10.250.0.3/32, 10.42.1.0/24\n'
                'Endpoint = '+endpoint.DIRECT+'\nPersistentKeepalive = 25\n\n'
                '[Peer]\nPublicKey = another-peer\nEndpoint = example.test:1234\n')

    def test_only_one_endpoint_changed(self):
        before = self.config()
        after = endpoint.replace_endpoint(before, endpoint.RELAY)
        self.assertEqual(after, before.replace(endpoint.DIRECT, endpoint.RELAY))
        self.assertEqual(endpoint.replace_endpoint(after, endpoint.DIRECT), before)

    def test_idempotent(self):
        once = endpoint.replace_endpoint(self.config(), endpoint.RELAY)
        self.assertEqual(endpoint.replace_endpoint(once, endpoint.RELAY), once)

    def test_unknown_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            endpoint.replace_endpoint(self.config().replace(endpoint.DIRECT, '192.0.2.1:1234'), endpoint.RELAY)

    def test_duplicate_peer_rejected(self):
        with self.assertRaises(ValueError):
            endpoint.replace_endpoint(self.config()+self.config(), endpoint.RELAY)

    def test_missing_peer_rejected(self):
        with self.assertRaises(ValueError):
            endpoint.replace_endpoint(self.config().replace(endpoint.PEER, 'absent'), endpoint.RELAY)

    def test_duplicate_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            endpoint.replace_endpoint(self.config().replace('Endpoint = '+endpoint.DIRECT, 'Endpoint = '+endpoint.DIRECT+'\nEndpoint = '+endpoint.DIRECT), endpoint.RELAY)

    def test_service_has_no_keys_or_privileged_capabilities(self):
        service = (ROOT / 'ansible/files/wg-peer15-relay.service').read_text()
        for required in ['DynamicUser=yes', 'NoNewPrivileges=yes', 'CapabilityBoundingSet=\n', 'IPAddressDeny=any', 'IPAddressAllow=10.250.0.41/32 192.168.0.24/32']:
            self.assertIn(required, service)
        self.assertNotIn('PrivateKey', service)
        relay = (ROOT / 'scripts/wg-peer15-relay.py').read_text()
        self.assertIn("FRONT = ('10.250.0.1', 51835)", relay)
        self.assertIn("CLIENT = ('10.250.0.41', 51830)", relay)
        self.assertIn("TARGET = ('192.168.0.24', 51830)", relay)
        self.assertIn('if source != CLIENT', relay)
        self.assertNotIn('0.0.0.0', relay)


if __name__ == '__main__':
    unittest.main()
