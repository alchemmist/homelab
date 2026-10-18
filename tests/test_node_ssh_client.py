import getpass
from pathlib import Path
import subprocess
import tempfile
import unittest

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


class NodeSshClientTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        template = Environment(undefined=StrictUndefined).from_string((ROOT / 'ansible/roles/node_ssh_client/templates/nodes.conf.j2').read_text())
        self.snippet = self.root / 'nodes.conf'
        self.snippet.write_text(template.render(homelab_node_ssh_hosts={'socrat-1': {'address': '10.250.0.3'}, 'socrat-3': {'address': '10.250.0.5', 'ssh_port': 2200}}, hostvars={'socrat-1': {'homelab_ssh_port': 2222}}, homelab_node_ssh_port=22))
        self.config = self.root / 'config'
        self.config.write_text(f'Include {self.snippet}\nServerAliveCountMax 7\n')

    def resolve(self, host, *args):
        result = subprocess.run(['ssh', '-G', '-F', str(self.config), *args, host], text=True, capture_output=True, check=True)
        return dict(line.split(' ', 1) for line in result.stdout.splitlines() if ' ' in line)

    def test_alias_keeps_current_user_and_default_identity_policy(self):
        node = self.resolve('socrat-1')
        baseline = self.resolve('example.invalid')
        self.assertEqual((node['hostname'], node['port'], node['user']), ('10.250.0.3', '2222', getpass.getuser()))
        for key in ('identityfile', 'identitiesonly', 'forwardagent', 'stricthostkeychecking'):
            self.assertEqual(node[key], baseline[key])

    def test_explicit_user_override_remains_supported(self):
        self.assertEqual(self.resolve('socrat-1', '-l', 'tim')['user'], 'tim')

    def test_per_node_port_override(self):
        node = self.resolve('socrat-3')
        self.assertEqual((node['hostname'], node['port']), ('10.250.0.5', '2200'))

    def test_include_does_not_leak_host_scope(self):
        node = self.resolve('example.invalid')
        self.assertEqual((node['hostname'], node['port'], node['serveralivecountmax']), ('example.invalid', '22', '7'))

    def test_personal_settings_have_priority(self):
        self.config.write_text(f'Host socrat-1\n    User custom-account\nHost *\n    Include {self.snippet}\n')
        self.assertEqual(self.resolve('socrat-1')['user'], 'custom-account')


if __name__ == '__main__':
    unittest.main()
