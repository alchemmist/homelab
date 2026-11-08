"""Local-only HTTP/Helm checks; never calls live cluster or inference."""
import http.client
import importlib.util
import json
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('queue_web', ROOT / 'charts/spi-triage/ui/queue_web.py')
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)
RealConnection = http.client.HTTPConnection

class QueueWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = web.Server(('127.0.0.1', 0), web.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(2)
    def request(self, method='GET', path='/queue/', body=None, extra=None):
        headers = {'Host': 'rustfs.socrat.alchemmist.xyz', 'X-authentik-groups': 'homelab-owner'}
        headers.update(extra or {})
        c = RealConnection('127.0.0.1', self.server.server_port, timeout=3)
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse(); result = (r.status, dict(r.headers), r.read()); c.close()
        return result
    def test_static_csp_and_no_framework(self):
        code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertIn('private, no-store', headers['Cache-Control'])
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertNotIn("'unsafe-inline'", headers['Content-Security-Policy'])
        self.assertNotIn(b'https://', body)
        js = (ROOT / 'charts/spi-triage/ui/app.js').read_text()
        self.assertNotIn('innerHTML', js)
        self.assertIn('textContent', js)
        self.assertIn('expected_updated', js)
    def test_host_group_and_arbitrary_path_denied(self):
        self.assertEqual(self.request(extra={'Host':'evil.invalid'})[0], 400)
        self.assertEqual(self.request(extra={'X-authentik-groups':'viewer'})[0], 403)
        self.assertEqual(self.request(path='/queue/../../service.py')[0], 404)
        self.assertEqual(self.request(path='/queue/app.js?x=1')[0], 404)
        self.assertEqual(self.request(path='/queue')[0], 308)
    def test_csrf_rejected_before_upstream(self):
        for extra in ({}, {'Origin':'https://evil.invalid', 'X-SPI-Queue':'1'},
                      {'Origin':web.ORIGIN, 'X-SPI-Queue':'1', 'Sec-Fetch-Site':'cross-site'}):
            with patch.object(web.http.client, 'HTTPConnection') as upstream:
                self.assertEqual(self.request('POST', '/queue/api/cancel', '{}', extra)[0], 403)
                upstream.assert_not_called()
    def test_fixed_upstream_and_no_cookie_identity_or_worker_header_forwarding(self):
        response = Mock(status=200)
        response.read.return_value = b'{"items":[],"counts":{}}'
        connection = Mock(); connection.getresponse.return_value = response
        headers = {'Origin':web.ORIGIN, 'X-SPI-Queue':'1', 'Content-Type':'application/json',
                   'Cookie':'opaque-test', 'X-Worker-Token':'must-not-forward'}
        with patch.object(web, 'TOKEN', 'local-fixture-token'), patch.object(web.http.client, 'HTTPConnection', return_value=connection) as factory:
            code, _, body = self.request('POST', '/queue/api/list', '{}', headers)
        self.assertEqual(code, 200)
        factory.assert_called_once_with('spi-triage.automation.svc.cluster.local', 8080, timeout=8)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ('POST', '/operator/queue/list'))
        self.assertEqual(set(kwargs['headers']), {'Content-Type', 'X-Queue-Token'})
        self.assertNotIn(b'local-fixture-token', body)
        connection.close.assert_called_once()
    def test_no_arbitrary_proxy_target_or_cors(self):
        headers = {'Origin':web.ORIGIN, 'X-SPI-Queue':'1', 'Content-Type':'application/json'}
        with patch.object(web.http.client, 'HTTPConnection') as upstream:
            self.assertEqual(self.request('POST', '/queue/api/claim', '{}', headers)[0], 404)
            upstream.assert_not_called()
        code, response_headers, _ = self.request('OPTIONS')
        self.assertEqual(code, 405)
        self.assertNotIn('Access-Control-Allow-Origin', response_headers)

class QueueHelmTests(unittest.TestCase):
    def test_private_routes_network_identity_and_separate_secret(self):
        raw = subprocess.check_output(['helm', 'template', 'spi-triage', str(ROOT/'charts/spi-triage'),
                    '-n', 'automation', '-f', str(ROOT/'charts/spi-triage/values-off-live.yaml')])
        docs = list(yaml.safe_load_all(raw))
        def get(kind, name):return next(d for d in docs if d and d['kind']==kind and d['metadata']['name']==name)
        ingress = get('Ingress', 'spi-queue-ui')
        self.assertEqual(ingress['spec']['rules'][0]['host'], 'rustfs.socrat.alchemmist.xyz')
        chain = ingress['metadata']['annotations']['traefik.ingress.kubernetes.io/router.middlewares'].split(',')
        self.assertIn('clean-identity', chain[0]); self.assertIn('queue-auth', chain[1])
        self.assertEqual(get('Middleware','spi-queue-clean-identity')['spec']['headers']['customRequestHeaders']['X-authentik-groups'], '')
        auth = get('Middleware','spi-queue-auth')['spec']['forwardAuth']
        self.assertFalse(auth['trustForwardHeader'])
        self.assertEqual(auth['authResponseHeaders'], ['X-authentik-groups'])
        pod = get('Deployment','spi-queue-ui')['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        container = pod['containers'][0]
        self.assertIn('@sha256:4cd6a12', container['image'])
        self.assertNotIn('env', container)
        self.assertEqual(pod['volumes'][1]['secret']['secretName'], 'spi-queue-control')
        self.assertEqual(container['volumeMounts'][1]['mountPath'], '/queue-control')
        net = get('NetworkPolicy','spi-queue-ui')['spec']
        self.assertEqual(net['ingress'][0]['from'][0]['podSelector']['matchLabels']['app.kubernetes.io/name'], 'traefik')
        self.assertEqual(net['egress'][0]['to'][0]['podSelector']['matchLabels'], {'app':'spi-triage'})
        self.assertFalse(any('ipBlock' in target for rule in net['egress'] for target in rule['to']))

if __name__ == '__main__':unittest.main()
