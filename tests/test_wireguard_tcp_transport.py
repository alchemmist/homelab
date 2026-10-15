import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / 'ansible/roles/wireguard_tcp_transport/files'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENDPOINT = load('endpoint')
HEALTH = load('health')
CONFIG = '[Interface]\nPrivateKey = secret\n\n[Peer]\nPublicKey = first\nAllowedIPs = 10.0.0.1/32, 192.168.0.24/32\nEndpoint = old:123\nPersistentKeepalive = 25\n\n[Peer]\nPublicKey = other\nEndpoint = other:123\n'


class TransportTests(unittest.TestCase):
    def test_preserves_secrets_other_peer_and_routes(self):
        expected = CONFIG.replace('Endpoint = old:123', 'Endpoint = 127.0.0.1:51840')
        self.assertEqual(ENDPOINT.update_config(CONFIG, 'first', '127.0.0.1:51840'), expected)
        self.assertEqual(ENDPOINT.update_config(expected, 'first', '127.0.0.1:51840'), expected)

    def test_server_removes_only_client_endpoint(self):
        self.assertEqual(ENDPOINT.update_config(CONFIG, 'first', ''), CONFIG.replace('Endpoint = old:123\n', ''))

    def test_missing_and_duplicate_peers_fail_closed(self):
        for original, key in [(CONFIG, 'missing'), (CONFIG + '\n[Peer]\nPublicKey = first\n', 'first')]:
            with self.assertRaises(ValueError):
                ENDPOINT.update_config(original, key, '')

    def test_saveconfig_fails_closed(self):
        with self.assertRaises(ValueError):
            ENDPOINT.update_config(CONFIG.replace('[Interface]', '[Interface]\nSaveConfig = true'), 'first', '')

    def test_three_failures_restart_and_cooldown(self):
        state = {}
        for now in (60, 75):
            state, restart = HEALTH.next_state(state, now, False)
            self.assertFalse(restart)
        state, restart = HEALTH.next_state(state, 90, False)
        self.assertTrue(restart)
        for now in (105, 120, 135):
            state, restart = HEALTH.next_state(state, now, False)
            self.assertFalse(restart)
        state, restart = HEALTH.next_state(state, 150, False)
        self.assertTrue(restart)

    def test_success_and_boot_grace(self):
        state, restart = HEALTH.next_state({'failures': 10}, 59, False)
        self.assertFalse(restart)
        state, restart = HEALTH.next_state(state, 70, True)
        self.assertEqual(state['failures'], 0)
        self.assertFalse(restart)


if __name__ == '__main__':
    unittest.main()
