from pathlib import Path
import json
import os
import shlex
import subprocess
import tempfile
import unittest

from jinja2 import Environment, StrictUndefined


ROLE = Path(__file__).resolve().parents[1] / 'ansible/roles/wireguard_private_web'
TASKS = (ROLE / 'tasks/main.yml').read_text()
DEFAULTS = (ROLE / 'defaults/main.yml').read_text()
SCRIPT = (ROLE / 'templates/wireguard-private-web.sh.j2').read_text()
UNIT = (ROLE / 'templates/wireguard-private-web.service.j2').read_text()


class WireGuardPrivateWebTests(unittest.TestCase):
    def test_defaults_are_disabled_and_use_nftables(self):
        self.assertIn('wireguard_private_web_enabled: false', DEFAULTS)
        self.assertIn('Debian: nftables', DEFAULTS)
        self.assertIn('Archlinux: nftables', DEFAULTS)
        self.assertIn('wireguard_private_web_proxy_port: 18443', DEFAULTS)

    def test_installs_and_starts_dedicated_unit(self):
        self.assertIn('ansible.builtin.apt', TASKS)
        self.assertIn('community.general.pacman', TASKS)
        self.assertIn('systemd_service', TASKS)
        self.assertIn('enabled: true', TASKS)
        self.assertIn('ExecStart={{ wireguard_private_web_script_path }}', UNIT)
        self.assertIn('RemainAfterExit=yes', UNIT)
        self.assertIn('Wants=network-online.target {{ wireguard_private_web_wg_service }}', UNIT)
        self.assertIn('After=network-online.target {{ wireguard_private_web_wg_service }}', UNIT)
        self.assertNotIn('ExecStop=', UNIT)

    def test_owns_only_its_nft_table_and_nat_hooks(self):
        self.assertIn('table={{ wireguard_private_web_table | quote }}', SCRIPT)
        self.assertIn('delete table ip $table', SCRIPT)
        self.assertIn('add chain ip %s prerouting { type nat hook prerouting priority -110; policy accept; }', SCRIPT)
        self.assertIn('add chain ip %s output { type nat hook output priority -110; policy accept; }', SCRIPT)
        self.assertIn('iifname %s ip daddr %s tcp dport %s dnat to %s:%s', SCRIPT)
        self.assertIn('output ip daddr %s tcp dport %s dnat to %s:%s', SCRIPT)
        self.assertNotIn('flush ruleset', SCRIPT)

    def test_validates_before_apply_and_preserves_an_owned_backup(self):
        self.assertIn('nft" -c -f "$tmp"', SCRIPT)
        self.assertIn('cp "$old" "$backup"', SCRIPT)
        self.assertIn('nft" -f "$tmp"', SCRIPT)
        self.assertNotIn('nft" -f "$backup"', SCRIPT)

    def test_failed_atomic_apply_does_not_append_backup_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            state = directory / 'state.json'
            state.write_text(json.dumps({'apply_calls': 0, 'rules': ['original']}))
            binary = directory / 'nft'
            binary.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['PRIVATE_WEB_TEST_STATE'])
s=json.loads(p.read_text())
if sys.argv[1] == 'list':
    print('table ip homelab_private_web { }')
    sys.exit(0)
if '-c' in sys.argv:
    (p.parent / 'validated.nft').write_text(Path(sys.argv[-1]).read_text())
    sys.exit(0)
s['apply_calls'] += 1
if s['apply_calls'] > 1:
    s['rules'].append('duplicate backup')
p.write_text(json.dumps(s))
sys.exit(1 if s['apply_calls'] == 1 else 0)
''')
            binary.chmod(0o755)
            environment = Environment(undefined=StrictUndefined)
            environment.filters['bool'] = bool
            environment.filters['quote'] = lambda value: shlex.quote(str(value))
            rendered = environment.from_string(SCRIPT).render(
                wireguard_private_web_binary_by_os_family={'Debian': str(binary)},
                ansible_os_family='Debian',
                wireguard_private_web_table='homelab_private_web',
                wireguard_private_web_interface='wg-socrat',
                wg_socrat_nodes={'socrat-0': {'address': '10.250.0.1'}},
                inventory_hostname='socrat-0',
                wireguard_private_web_public_port=443,
                wireguard_private_web_proxy_port=18443,
                wireguard_private_web_backup_path=str(directory / 'backup.nft'),
                wireguard_private_http_enabled=False,
                wireguard_private_web_pod_cidrs=['10.42.0.0/16'],
            )
            result = subprocess.run(
                ['/bin/sh', '-c', rendered], capture_output=True, text=True,
                env={**os.environ, 'PRIVATE_WEB_TEST_STATE': str(state)},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(state.read_text()), {'apply_calls': 1, 'rules': ['original']})
            self.assertTrue((directory / 'backup.nft').exists())
            rules = (directory / 'validated.nft').read_text()
            self.assertIn('prerouting iifname cni0 ip saddr 10.42.0.0/16 ip daddr 10.250.0.1 tcp dport 443 dnat to 10.250.0.1:18443', rules)
            self.assertNotIn('192.168.', rules)


if __name__ == '__main__':
    unittest.main()
