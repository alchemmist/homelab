from pathlib import Path
import unittest


ROLE = Path(__file__).resolve().parents[1] / 'ansible/roles/wireguard_admin_client'
TASKS = (ROLE / 'tasks/main.yml').read_text()
DEFAULTS = (ROLE / 'defaults/main.yml').read_text()
TEMPLATE = (ROLE / 'templates/wg-socrat-admin.conf.j2').read_text()
ROLLBACK = (ROLE / 'ROLLBACK.md').read_text()


class WireGuardAdminClientTests(unittest.TestCase):
    def test_profile_has_three_direct_peers_and_exact_endpoints(self):
        self.assertEqual(TEMPLATE.count('[Peer]'), 1)
        self.assertIn("{% for peer in wireguard_admin_peers %}", TEMPLATE)
        self.assertIn('AllowedIPs = {{ peer.address }}/32', TEMPLATE)
        self.assertIn('PersistentKeepalive = {{ wireguard_admin_keepalive }}', TEMPLATE)
        for endpoint in ('109.173.40.247:51830', '109.173.40.247:51831', '176.98.185.59:51830'):
            self.assertIn(endpoint, DEFAULTS)

    def test_profile_does_not_capture_dns(self):
        self.assertNotIn('DNS', TEMPLATE)
        self.assertNotIn('0.0.0.0/0', TEMPLATE)

    def test_private_key_is_generated_and_managed_without_logging(self):
        self.assertIn('wg genkey', TASKS)
        self.assertIn('ansible.builtin.command: wg pubkey', TASKS)
        self.assertIn('stdin: "{{ wireguard_admin_private_key }}\\n"', TASKS)
        self.assertNotIn('ansible.builtin.shell:', TASKS)
        self.assertIn("mode: '0600'", TASKS)
        self.assertGreaterEqual(TASKS.count('no_log: true'), 5)
        self.assertIn('wg_socrat_nodes', DEFAULTS)

    def test_peer_defaults_are_distinct_bare_addresses_and_keys_come_from_inventory(self):
        self.assertIn("item.address is match", TASKS)
        self.assertIn("item.address is not search('/')", TASKS)
        self.assertIn('public_key is match', TASKS)
        self.assertIn('public_key | length > 0', TASKS)
        for name in ('socrat-0', 'socrat-1', 'socrat-2'):
            self.assertIn(f"get('{name}', {{}}).get('public_key', '')", DEFAULTS)

    def test_dns_is_privileged_and_scoped_to_dns_tag(self):
        self.assertGreaterEqual(TASKS.count('become: true'), 4)
        self.assertGreaterEqual(TASKS.count('tags: dns'), 4)
        for resolver in ('0.socrat.alchemmist.xyz', '1.socrat.alchemmist.xyz', '2.socrat.alchemmist.xyz'):
            self.assertIn(resolver, TASKS)
        self.assertIn('/etc/resolv.conf', ROLLBACK)
        self.assertIn('unrelated files', ROLLBACK)


if __name__ == '__main__':
    unittest.main()
