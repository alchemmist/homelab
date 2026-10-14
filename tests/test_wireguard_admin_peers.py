import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / 'ansible/roles/wireguard_socrat/templates'
TASKS = TEMPLATE_DIR.parent / 'tasks/main.yml'


class WireGuardTemplateTests(unittest.TestCase):
    def setUp(self):
        if shutil.which('ansible-playbook') is None:
            self.skipTest('ansible-playbook is unavailable')
        self.nodes = {
            'socrat-0': {'address': '10.250.0.1', 'public_key': 'node0'},
            'socrat-1': {
                'address': '10.250.0.3',
                'public_key': 'node1',
                'endpoint': '192.168.0.24:51830',
            },
            'socrat-2': {
                'address': '10.250.0.2',
                'public_key': 'node2',
                'endpoint': '176.98.185.59:51830',
            },
        }

    def render(self, host, clients=None, nodes=None, peer_endpoints=None):
        variables = {
            'inventory_hostname': host,
            'wg_socrat_nodes': nodes or self.nodes,
            'wg_socrat_admin_clients': clients or {},
            'wg_socrat_peer_endpoints': peer_endpoints or {},
            'wg_socrat_port': 51830,
            'wg_socrat_keepalive': 25,
            'wg_socrat_private_key': 'private',
        }
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            playbook = directory / 'render.yml'
            variables_file = directory / 'vars.json'
            output = directory / 'wg-socrat.conf'
            playbook.write_text(
                '---\n'
                '- hosts: all\n'
                '  gather_facts: false\n'
                '  tasks:\n'
                '    - ansible.builtin.template:\n'
                f'        src: {TEMPLATE_DIR / "wg-socrat.conf.j2"}\n'
                f'        dest: {output}\n'
            )
            variables_file.write_text(json.dumps(variables))
            subprocess.run(
                [
                    'ansible-playbook', '-i', 'localhost,', '-c', 'local',
                    '-e', f'@{variables_file}', str(playbook),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return output.read_text()

    def test_admin_client_is_rendered_as_a_host_route_without_endpoint(self):
        config = self.render('socrat-2', {
            'macbook': {'address': '10.250.0.4', 'public_key': 'mac-key'},
        })
        self.assertIn('# macbook\nPublicKey = mac-key\nAllowedIPs = 10.250.0.4/32', config)
        self.assertNotIn('Endpoint =', config.split('# macbook', 1)[1].split('[Peer]', 1)[0])

    def test_local_peer_endpoint_override_can_omit_unreachable_lan_endpoint(self):
        config = self.render('socrat-2', peer_endpoints={'socrat-2': {'socrat-1': ''}})
        peer = config.split('# socrat-1', 1)[1].split('[Peer]', 1)[0]
        self.assertNotIn('Endpoint =', peer)

    def test_existing_peer_endpoint_remains_the_default(self):
        config = self.render('socrat-2')
        peer = config.split('# socrat-1', 1)[1].split('[Peer]', 1)[0]
        self.assertIn('Endpoint = 192.168.0.24:51830', peer)

    def test_selected_key_is_validated_before_configuration_render(self):
        tasks = TASKS.read_text()
        self.assertLess(
            tasks.index('Verify selected wg-socrat public key before applying changes'),
            tasks.index('Render wg-socrat config'),
        )
        self.assertIn('wg_socrat_derived_public_key.stdout | trim == wg_socrat_nodes[inventory_hostname].public_key', tasks)
        generation = tasks[tasks.index('Generate wg-socrat private key if missing'):tasks.index('Store wg-socrat private key fact')]
        self.assertIn('wg_socrat_runtime_private_key.rc != 0', generation)


if __name__ == '__main__':
    unittest.main()
