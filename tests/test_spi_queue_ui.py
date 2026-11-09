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
RealAuthorization = web.Handler.authorization

class QueueWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth_patch = patch.object(web.Handler, 'authorization', return_value=200)
        cls.auth_patch.start()
        cls.server = web.Server(('127.0.0.1', 0), web.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(2)
        cls.auth_patch.stop()
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
        self.assertEqual(self.request(path='/queue/../../service.py')[0], 404)
        self.assertEqual(self.request(path='/queue/app.js?x=1')[0], 404)
        self.assertEqual(self.request(path='/queue')[0], 308)
    def test_anonymous_challenge_returns_exact_queue_and_does_not_trust_identity_header(self):
        with patch.object(web.Handler, 'authorization', return_value=401):
            code, headers, _ = self.request(extra={'X-authentik-groups':'homelab-owner'})
        self.assertEqual(code, 302)
        self.assertEqual(web.urllib.parse.parse_qs(web.urllib.parse.urlsplit(headers['Location']).query)['rd'], [web.ORIGIN + '/queue/'])

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

class QueueAuthorizationTests(unittest.TestCase):
    def test_caller_groups_never_authorize_without_real_cookie(self):
        from email.message import Message
        handler = Mock(); handler.headers = Message(); handler.headers['X-authentik-groups'] = 'homelab-owner'
        with patch.object(web.AUTH, 'open') as auth:
            self.assertEqual(RealAuthorization(handler), 401)
            auth.assert_not_called()

    def test_only_trusted_auth_response_groups_grant_access(self):
        from email.message import Message
        handler = Mock(); handler.headers = Message()
        handler.headers['Cookie'] = 'opaque-local-session-fixture'
        handler.headers['X-authentik-groups'] = 'homelab-owner'
        with patch.object(web.AUTH, 'open') as auth:
            response = auth.return_value.__enter__.return_value
            response.status = 204; response.headers = {'X-authentik-groups':'viewer'}
            self.assertEqual(RealAuthorization(handler), 403)
            response.headers = {'X-authentik-groups':'homelab-owner'}
            self.assertEqual(RealAuthorization(handler), 200)
            request = auth.call_args.args[0]
            self.assertEqual(request.full_url, web.ORIGIN + '/outpost.goauthentik.io/auth/nginx')
            self.assertEqual(request.get_header('Cookie'), 'opaque-local-session-fixture')
        with patch.object(web.AUTH, 'open', side_effect=OSError()):
            self.assertEqual(RealAuthorization(handler), 503)

class QueueHelmTests(unittest.TestCase):
    def test_private_routes_network_identity_and_separate_secret(self):
        raw = subprocess.check_output(['helm', 'template', 'spi-triage', str(ROOT/'charts/spi-triage'),
                    '-n', 'automation', '-f', str(ROOT/'charts/spi-triage/values-off-live.yaml')])
        docs = list(yaml.safe_load_all(raw))
        def get(kind, name):return next(d for d in docs if d and d['kind']==kind and d['metadata']['name']==name)
        ingress = get('Ingress', 'spi-queue-ui')
        self.assertEqual(ingress['spec']['rules'][0]['host'], 'rustfs.socrat.alchemmist.xyz')
        self.assertNotIn('traefik.ingress.kubernetes.io/router.middlewares', ingress['metadata']['annotations'])
        # Cookie is verified directly at the same fixed TLS endpoint as Reader.
        self.assertIn("'/outpost.goauthentik.io/auth/nginx'", (ROOT/'charts/spi-triage/ui/queue_web.py').read_text())
        pod = get('Deployment','spi-queue-ui')['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname':'socrat-3'})
        container = pod['containers'][0]
        self.assertIn('@sha256:4cd6a12', container['image'])
        self.assertNotIn('env', container)
        self.assertEqual(pod['volumes'][1]['secret']['secretName'], 'spi-queue-control')
        self.assertEqual(container['volumeMounts'][1]['mountPath'], '/queue-control')
        net = get('NetworkPolicy','spi-queue-ui')['spec']
        self.assertEqual(net['ingress'][0]['from'][0]['podSelector']['matchLabels']['app.kubernetes.io/name'], 'traefik')
        self.assertTrue(any(target.get('podSelector',{}).get('matchLabels')=={'app':'spi-triage'} for rule in net['egress'] for target in rule['to']))
        cidrs = {target['ipBlock']['cidr'] for rule in net['egress'] for target in rule['to'] if 'ipBlock' in target}
        self.assertEqual(cidrs, {'109.173.40.247/32','109.120.141.60/32'})
        for rule in net['egress']:
            if any('ipBlock' in target for target in rule['to']):self.assertEqual(rule['ports'], [{'port':443,'protocol':'TCP'}])

if __name__ == '__main__':unittest.main()
