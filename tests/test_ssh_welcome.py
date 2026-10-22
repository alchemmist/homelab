import importlib.util
import json
import re
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('welcome', ROOT / 'ansible/roles/ssh_welcome/files/welcome.py')
WELCOME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WELCOME)


class WelcomeTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(node='socrat-3', labels={}, addresses=[dict(type='InternalIP', address='10.250.0.5')], description='Old MSI', admin='alchemmist', contacts={}, rancher_url='https://rancher.socrat.alchemmist.xyz', cluster='local', exporter_port=9796, logo='reference-16')
        self.portraits = json.loads((ROOT / 'assets/socrates-braille.json').read_text())

    def test_etcd_is_not_reported_as_worker(self):
        self.assertEqual(WELCOME.role({'node-role.kubernetes.io/etcd': 'true'}), 'etcd')
        self.assertEqual(WELCOME.role({'node-role.kubernetes.io/control-plane': '', 'node-role.kubernetes.io/etcd': ''}), 'master + etcd')
        self.assertEqual(WELCOME.role({}), 'worker')

    def test_links_target_current_node(self):
        monitoring, rancher = WELCOME.urls(self.config, '10.250.0.5')
        self.assertEqual(parse_qs(urlsplit(monitoring).query)['var-instance'], ['10.250.0.5:9796'])
        self.assertTrue(rancher.endswith('/node/socrat-3'))

    def test_description_cannot_inject_terminal_commands(self):
        self.config['description'] = 'MSI\x1b]52;clipboard\x07\nnext'
        result = WELCOME.render(self.config, self.portraits, [], 100, False, False)
        self.assertNotIn('\x1b', result)
        self.assertNotIn('\x07', result)
        self.assertIn('MSI', result)

    def test_small_terminal_stacks_information(self):
        result = WELCOME.render(self.config, self.portraits, [], 50, False, True)
        self.assertIn('Internal IP: 10.250.0.5', result)
        self.assertIn('Description: Old MSI', result)
        self.assertIn('This node is managed by the root user alchemmist.', ' '.join(result.split()))
        self.assertIn('anton.ingrish@gmail.com', result)
        self.assertIn('@alchemmist', result)
        self.assertTrue(all(len(line) <= 50 for line in result.splitlines() if '\x1b' not in line))

    def test_default_terminal_output_has_visible_urls_without_osc8(self):
        result = WELCOME.render(self.config, self.portraits, [])
        monitoring, rancher = WELCOME.urls(self.config, '10.250.0.5')
        self.assertIn('\033[1mMonitoring:\033[0m', result)
        self.assertIn('\033[1mRancher:\033[0m', result)
        plain = re.sub(r'\x1b\[[0-9;]*m', '', result)
        logo_width = max(len(line.rstrip()) for line in self.portraits['variants'][0]['lines'])
        column = [line[logo_width + 4:] for line in plain.splitlines() if line.startswith('  ')]
        joined = ''.join(line.strip() for line in column)
        self.assertIn(monitoring, joined.replace('Monitoring: ', ''))
        self.assertIn(rancher, joined.replace('Rancher: ', ''))
        self.assertLess(plain.index('Description:'), plain.index('Monitoring:'))
        self.assertLess(plain.index('Monitoring:'), plain.index('Rancher:'))
        self.assertLess(plain.index('Rancher:'), plain.index('This node is managed'))
        self.assertTrue(all(len(line) <= 100 for line in plain.splitlines()))
        self.assertNotIn('\033]8;', result)
        self.assertNotIn('Admin:', result)
        self.assertNotIn('see link below', result)

    def test_admin_note_is_compact_on_wide_terminal(self):
        result = WELCOME.render(self.config, self.portraits, [], 180, False, False)
        note = result[result.index('This node is managed'):].strip()
        self.assertTrue(all(len(line) <= 76 for line in note.splitlines()))
        self.assertIn('More info about cluster on https://wiki.socrat.alchemmist.xyz/', ' '.join(note.split()))
        self.assertIn('https://wiki.socrat.alchemmist.xyz/', note)

    def test_plain_output_retains_full_urls(self):
        result = WELCOME.render(self.config, self.portraits, [('RAM', '13 / 32 GiB used')], 110, False, False)
        self.assertIn('RAM: 13 / 32 GiB used', result)
        self.assertIn('Monitoring: https://', result)
        self.assertNotIn('\x1b', result)


if __name__ == '__main__':
    unittest.main()
