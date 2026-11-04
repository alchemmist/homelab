"""Offline chart rendering and real nginx parser tests; no cluster access."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ('private-gateway', 'syncthing', 'img-proxy', 'litellm-infra', 'socrat-home')


class SafeNginxLoggingTests(unittest.TestCase):
    def render(self, chart):
        return list(yaml.safe_load_all(subprocess.check_output(
            ['helm', 'template', 'test', str(ROOT / 'charts' / chart)] +
            (['--set', 'privateGui.enabled=true'] if chart == 'syncthing' else []), text=True)))

    def test_render_and_safe_contract(self):
        for chart in CHARTS:
            with self.subTest(chart=chart):
                docs = self.render(chart)
                configs = [v for d in docs if d and d['kind'] == 'ConfigMap'
                           for v in d.get('data', {}).values() if 'log_format safe_json' in v]
                self.assertTrue(configs)
                for config in configs:
                    fmt = re.search(r"log_format safe_json escape=json '([^']+)';", config).group(1)
                    for forbidden in ('$request_uri', '$request"', '$args', '$http_', '$remote_addr', '$cookie_'):
                        self.assertNotIn(forbidden, fmt)
                    self.assertIn('"path":"$uri"', fmt)
                    self.assertIn('"timestamp":"$time_iso8601"', fmt)
                    self.assertIn('~^4 warn;', config)
                    self.assertIn('~^5 error;', config)
                    self.assertIn('access_log /dev/stdout safe_json;', config)

    @unittest.skipUnless(shutil.which('docker'), 'docker required for nginx syntax validation')
    def test_real_nginx_http_syntax(self):
        # Extract exact rendered logging directives; TLS/listen/upstream resources
        # in full gateway configs depend on deployment-only IPs and secrets.
        for chart in CHARTS:
            configs = [v for d in self.render(chart) if d and d['kind'] == 'ConfigMap'
                       for v in d.get('data', {}).values() if 'log_format safe_json' in v]
            for config in configs:
                block = re.search(r'map \$status.*?access_log /dev/stdout safe_json;', config, re.S).group()
                candidate = 'events {}\nhttp {\n' + block + '\nserver { listen 8080; return 204; }\n}\n'
                result = subprocess.run(['docker', 'run', '--rm', '-i', '--network=none',
                    '--entrypoint', 'sh', 'nginx:1.28.0-alpine', '-c',
                    'cat > /tmp/test.conf; TZ=UTC nginx -t -c /tmp/test.conf'],
                    input=candidate, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, f'{chart}: nginx syntax rejected')

    def test_socrat_mount_without_homepage(self):
        output = subprocess.check_output(['helm', 'template', 'test', str(ROOT / 'charts/socrat-home'),
                                          '--set', 'homepageIndex.enabled=false'], text=True)
        deployment = next(d for d in yaml.safe_load_all(output) if d and d['kind'] == 'Deployment')
        pod = deployment['spec']['template']
        self.assertIn('checksum/access-logging', pod['metadata']['annotations'])
        self.assertEqual(pod['spec']['volumes'][0]['name'], 'access-logging')
        self.assertIn('/etc/nginx/conf.d/00-access-logging.conf',
                      [m['mountPath'] for m in pod['spec']['containers'][0]['volumeMounts']])
