from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'ansible/roles/homelab_private_dns'


class PrivateDnsRoleTests(unittest.TestCase):
    def setUp(self):
        self.defaults = (ROLE / 'defaults/main.yml').read_text()
        self.tasks = (ROLE / 'tasks/main.yml').read_text()
        self.config = (ROLE / 'templates/dnsmasq.conf.j2').read_text()
        self.unit = (ROLE / 'templates/homelab-private-dns.service.j2').read_text()

    def test_role_has_separate_service_and_config(self):
        self.assertIn('homelab_private_dns_unit_name: homelab-private-dns.service', self.defaults)
        self.assertIn('homelab_private_dns_config_path: /etc/homelab-private-dns.conf', self.defaults)
        self.assertIn('dest: "/etc/systemd/system/{{ homelab_private_dns_unit_name }}"', self.tasks)

    def test_dnsmasq_is_bound_to_wireguard_address_and_has_no_upstream(self):
        self.assertIn('listen-address={{ homelab_private_dns_listen_address }}', self.config)
        self.assertIn('bind-dynamic', self.config)
        self.assertIn('except-interface=lo', self.config)
        self.assertNotIn('interface={{ homelab_private_dns_interface }}', self.config)
        self.assertIn('no-resolv', self.config)
        self.assertIn('no-hosts', self.config)
        self.assertNotIn('address=/#/', self.config)
        self.assertNotIn('server=', self.config)

    def test_records_are_rendered_as_explicit_addresses(self):
        self.assertRegex(self.config, r'host-record=\{\{ record\.name \}\},\{\{ record\.address \}\}')
        self.assertIn('local=/{{ record.name }}/', self.config)
        self.assertNotIn('address=/{{ record.name }}/{{ record.address }}', self.config)
        self.assertIn("homelab_private_dns_records | sort(attribute='name')", self.config)

    def test_wireguard_lifecycle_is_part_of_private_dns_unit(self):
        self.assertIn('Requires={{ homelab_private_dns_wg_service }}', self.unit)
        self.assertIn('After=network-online.target {{ homelab_private_dns_wg_service }}', self.unit)
        self.assertIn('PartOf={{ homelab_private_dns_wg_service }}', self.unit)
        self.assertIn('BindsTo={{ homelab_private_dns_wg_service }}', self.unit)

    def test_configuration_is_validated_before_start_and_restart(self):
        self.assertIn('--test', self.tasks)
        self.assertIn('ExecStartPre={{ homelab_private_dns_binary }} --test', self.unit)
        self.assertIn('--keep-in-foreground', self.unit)
        self.assertIn('- name: Restart private DNS', (ROLE / 'handlers/main.yml').read_text())

    def test_platform_paths_cover_supported_hosts(self):
        self.assertIn('Debian: dnsmasq-base', self.defaults)
        self.assertIn('Archlinux: /usr/bin/dnsmasq', self.defaults)
        self.assertIn('homelab_private_dns_user: homelab-dns', self.defaults)
        self.assertIn('homelab_private_dns_group: homelab-dns', self.defaults)
        self.assertIn('when: ansible_os_family == \'Debian\'', self.tasks)
        self.assertIn('when: ansible_os_family == \'Archlinux\'', self.tasks)

    def test_template_validates_before_replacing_live_configuration(self):
        self.assertIn('validate: "{{ homelab_private_dns_binary }} --test --conf-file=%s"', self.tasks)

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook is required')
    def test_ansible_accepts_valid_private_dns_values(self):
        result = self.run_validation({
            'homelab_private_dns_listen_address': '10.250.0.1',
            'homelab_private_dns_records': [
                {'name': '0.socrat.alchemmist.xyz', 'address': '10.250.0.1'},
                {'name': '1.socrat.alchemmist.xyz', 'address': '10.250.0.3'},
                {'name': '2.socrat.alchemmist.xyz', 'address': '10.250.0.2'},
            ],
        })
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook is required')
    def test_ansible_rejects_invalid_private_dns_values(self):
        result = self.run_validation({
            'homelab_private_dns_listen_address': '10.250.0.999',
            'homelab_private_dns_records': [
                {'name': 'bad name', 'address': '10.250.0.1'},
            ],
        })
        self.assertNotEqual(result.returncode, 0)

    def run_validation(self, variables):
        playbook = '''
- hosts: localhost
  connection: local
  gather_facts: true
  roles:
    - homelab_private_dns
'''
        with tempfile.TemporaryDirectory() as directory:
            playbook_path = Path(directory) / 'validate.yml'
            playbook_path.write_text(playbook)
            command = [
                'ansible-playbook', str(playbook_path),
                '--tags', 'homelab_private_dns_validate',
                '-i', 'localhost,',
                '-e', 'ansible_os_family=Debian',
            ]
            command.extend(['-e', json.dumps({'ansible_os_family': 'Debian', **variables})])
            return subprocess.run(
                command,
                cwd=ROOT,
                env={**os.environ, 'ANSIBLE_ROLES_PATH': str(ROOT / 'ansible/roles')},
                capture_output=True,
                text=True,
                check=False,
            )


if __name__ == '__main__':
    unittest.main()
