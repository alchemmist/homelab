import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'ansible/roles/home_ingress_ha'


class KeepalivedStartupTest(unittest.TestCase):
    def run_wait(self, appear_at):
        script = (ROLE / 'templates/wait-home-ingress-interface.sh.j2').read_text()
        script = script.replace('{{ home_ingress_ha_nodes[inventory_hostname].interface | quote }}', 'wlan0')
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'ip').write_text(
                '#!/bin/sh\n'
                'n=0; [ ! -f "$STATE" ] || n=$(cat "$STATE")\n'
                'n=$((n+1)); echo "$n" > "$STATE"\n'
                '[ "$1 $2 $3 $4" = "link show dev wlan0" ] || exit 2\n'
                f'[ "$n" -ge {appear_at} ]\n')
            (directory / 'sleep').write_text('#!/bin/sh\nexit 0\n')
            for name in ('ip', 'sleep'):
                (directory / name).chmod(0o755)
            result = subprocess.run(['/bin/sh', '-c', script], capture_output=True, text=True,
                                    env={**os.environ, 'PATH': f'{tmp}:/usr/bin:/bin',
                                         'STATE': str(directory / 'state')}, timeout=5)
            return result, int((directory / 'state').read_text())

    def test_existing_interface_starts_immediately(self):
        result, attempts = self.run_wait(1)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(attempts, 1)

    def test_late_interface_is_waited_for(self):
        result, attempts = self.run_wait(4)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(attempts, 4)

    def test_missing_interface_fails_after_bounded_wait(self):
        result, attempts = self.run_wait(100)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(attempts, 60)
        self.assertIn('did not appear', result.stderr)

    def test_service_retries_and_has_time_for_prestart(self):
        override = (ROLE / 'templates/keepalived-startup.conf.j2').read_text()
        for setting in ('After=network-online.target', 'Restart=on-failure',
                        'RestartSec=15s', 'TimeoutStartSec=90s', 'StartLimitIntervalSec=0'):
            self.assertIn(setting, override)
        tasks = (ROLE / 'tasks/main.yml').read_text()
        self.assertIn('daemon_reload: true', tasks)


if __name__ == '__main__':
    unittest.main()
