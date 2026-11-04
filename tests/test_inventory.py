"""Local inventory contracts; these tests never connect to managed hosts."""
import configparser
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / 'ansible'
NODES = {f'socrat-{i}' for i in range(4)}


class InventoryStructureTests(unittest.TestCase):
    def test_main_inventory_contains_every_node_and_only_connection_settings(self):
        inventory = yaml.safe_load((ANSIBLE / 'inventory/hosts.yml').read_text())
        hosts = inventory['all']['children']['Socrat']['hosts']
        self.assertEqual(set(hosts), NODES)
        for host, settings in hosts.items():
            self.assertTrue(all(key.startswith('ansible_') for key in settings), host)
            self.assertTrue((ANSIBLE / 'inventory/host_vars' / f'{host}.yml').is_file())

    def test_default_sources_are_explicit_not_the_whole_inventory_directory(self):
        config = configparser.ConfigParser()
        config.read(ANSIBLE / 'ansible.cfg')
        self.assertEqual([s.strip() for s in config['defaults']['inventory'].split(',')],
                         ['inventory/hosts.yml', 'inventory/netbird-controller.yml'])
        self.assertFalse((ANSIBLE / 'inventory/socrat-3.yml').exists())


@unittest.skipUnless(shutil.which('ansible-inventory'), 'ansible-inventory is required')
class ResolvedInventoryTests(unittest.TestCase):
    def inventory(self, *sources):
        command = ['ansible-inventory']
        for source in sources:
            command += ['-i', f'inventory/{source}.yml']
        result = subprocess.run(command + ['--list'], cwd=ANSIBLE, check=True,
                                capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)

    def test_default_and_explicit_main_inventory_include_all_nodes(self):
        for sources in [(), ('hosts',)]:
            with self.subTest(sources=sources):
                data = self.inventory(*sources)
                self.assertEqual(set(data['Socrat']['hosts']), NODES)
                host = data['_meta']['hostvars']['socrat-3']
                self.assertEqual(host['ansible_host'], '10.250.0.5')
                self.assertEqual(host['ansible_port'], 2222)
                self.assertEqual(host['homelab_boot_k3s_service'], 'k3s-agent.service')
                self.assertTrue(host['k3s_worker_swap_enabled'])
        self.assertNotIn('netbird-controller', data['Socrat']['hosts'])
        self.assertIn('netbird-controller', self.inventory()['_meta']['hostvars'])

    def test_connection_overlays_still_override_main_inventory(self):
        for overlay, expected in {
            'direct': {'socrat-0': ('192.168.0.23', 22),
                       'socrat-1': ('192.168.0.24', 2222),
                       'socrat-2': ('176.98.185.59', 22)},
            'lan': {'socrat-0': ('192.168.0.23', 2222),
                    'socrat-1': ('192.168.0.24', 2222)},
        }.items():
            with self.subTest(overlay=overlay):
                data = self.inventory('hosts', overlay)
                self.assertEqual(set(data['Socrat']['hosts']), NODES)
                for node, connection in expected.items():
                    host = data['_meta']['hostvars'][node]
                    self.assertEqual((host['ansible_host'], host['ansible_port']), connection)
                self.assertEqual(data['_meta']['hostvars']['socrat-3']['ansible_host'], '10.250.0.5')


if __name__ == '__main__':
    unittest.main()
