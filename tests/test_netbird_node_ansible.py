from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class NodeAnsibleTest(unittest.TestCase):
    def test_baseline_and_membership_playbooks_include_onboarding(self):
        for name in ['base.yml', 'site.yml', 'k3s-worker.yml', 'k3s-ha.yml', 'netbird-nodes.yml']:
            plays = yaml.safe_load((ROOT/'ansible/playbooks'/name).read_text())
            self.assertTrue(any('netbird_node' in p.get('roles', []) for p in plays), name)

    def test_controller_connection_is_strict_and_outside_node_group(self):
        v = yaml.safe_load((ROOT/'ansible/inventory/netbird-controller.yml').read_text())
        self.assertNotIn('children', v['all'])
        connection = v['all']['hosts']['netbird-controller']
        self.assertEqual(connection['ansible_host'], '109.173.40.247')
        self.assertIn('StrictHostKeyChecking=yes', connection['ansible_ssh_common_args'])
        self.assertIn('HostKeyAlias=', connection['ansible_ssh_common_args'])
        defaults = yaml.safe_load((ROOT/'ansible/roles/netbird_node/defaults/main.yml').read_text())
        self.assertTrue(defaults['netbird_node_enabled'])
        self.assertEqual(defaults['netbird_node_controller'], 'netbird-controller')
        self.assertEqual(defaults['netbird_node_bootstrap_token_file'], '')
        self.assertEqual(defaults['netbird_node_adopt_state'], '')

    def test_inventory_scope_not_limited_to_one_requested_host(self):
        tasks = yaml.safe_load((ROOT/'ansible/roles/netbird_node/tasks/main.yml').read_text())[0]['block']
        template = next(t['ansible.builtin.copy']['content'] for t in tasks
                        if t.get('ansible.builtin.copy', {}).get('dest', '').endswith('/inventory.json'))
        self.assertIn("groups['Socrat']", template)
        self.assertNotIn('ansible_play_hosts', template)
        self.assertIn('reserved_addresses', template)
        self.assertIn('wg_socrat_admin_clients', template)
        cfg = (ROOT/'ansible/ansible.cfg').read_text()
        self.assertIn('inventory/hosts.yml', cfg)
        self.assertIn('inventory/netbird-controller.yml', cfg)

    def test_token_timer_is_not_permission_replay(self):
        tasks = yaml.safe_load((ROOT/'ansible/roles/netbird_node/tasks/main.yml').read_text())[0]['block']
        service = next(t['ansible.builtin.copy']['content'] for t in tasks
                       if t.get('ansible.builtin.copy', {}).get('dest', '').endswith('credential.service'))
        self.assertIn('netbird-node-credential.py', service)
        self.assertNotIn('netbird-node-reconcile.py', service)
        self.assertIn('ProtectSystem=strict', service)
        credential = next(t for t in tasks if t.get('no_log'))
        self.assertTrue(credential['no_log'])
