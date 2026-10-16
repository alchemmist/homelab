import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = shutil.which('ansible-playbook')


@unittest.skipUnless(ANSIBLE, 'ansible-playbook is required')
class WorkerAdmissionSafetyTests(unittest.TestCase):
    def assert_rejected_before_host_changes(self, hostname, os_family='Debian', address='10.250.0.5'):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            inventory = directory / 'inventory.json'
            inventory.write_text(json.dumps({
                'all': {'hosts': {hostname: {'ansible_connection': 'local'}}}
            }))
            playbook = directory / 'playbook.json'
            playbook.write_text(json.dumps([{
                'hosts': 'all',
                'gather_facts': False,
                'vars': {
                    'k3s_worker_name': hostname,
                    'ansible_facts': {'os_family': os_family, 'architecture': 'x86_64'},
                    'wg_socrat_nodes': {hostname: {'address': address}},
                },
                'roles': [str(ROOT / 'ansible/roles/k3s_worker')],
            }]))
            config = directory / 'ansible.cfg'
            config.write_text('[defaults]\n')
            environment = dict(os.environ, ANSIBLE_NOCOLOR='1', ANSIBLE_CONFIG=str(config))
            result = subprocess.run(
                [ANSIBLE, '-i', str(inventory), str(playbook), '--check'],
                cwd=temporary,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn('Restrict worker provisioning to its dedicated Debian host', output)
            self.assertIn('Assertion failed', output)
            self.assertNotIn('Inspect existing server datastore', output)

    def test_existing_control_planes_remain_rejected_when_worker_name_is_overridden(self):
        for hostname in ['socrat-0', 'socrat-1', 'socrat-2']:
            with self.subTest(hostname=hostname):
                self.assert_rejected_before_host_changes(hostname)

    def test_wrong_operating_system_is_rejected_before_package_operations(self):
        self.assert_rejected_before_host_changes('socrat-3', os_family='Archlinux')

    def test_management_address_mismatch_is_rejected_before_network_operations(self):
        self.assert_rejected_before_host_changes('socrat-3', address='10.250.0.4')


if __name__ == '__main__':
    unittest.main()
