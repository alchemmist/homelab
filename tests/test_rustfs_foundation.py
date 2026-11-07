"""Offline foundation safety checks; not runtime acceptance."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Foundation(unittest.TestCase):
    def render(self, *args):
        return subprocess.check_output(
            ['helm', 'template', 'rustfs', str(ROOT / 'charts/rustfs'), *args],
            text=True)

    def test_default_is_off(self):
        self.assertEqual(self.render().strip(), '')

    def test_retention_and_placement(self):
        text = self.render('--set', 'enabled=true')
        self.assertEqual(text.count('Prune=false,Delete=false'), 2)
        self.assertIn('reclaimPolicy: Retain', text)
        self.assertIn('volumeBindingMode: WaitForFirstConsumer', text)
        self.assertIn('kubernetes.io/hostname: socrat-0', text)
        self.assertNotIn('nodeName:', text)
        self.assertIn('storage: 20Gi', text)

    def test_no_exposure(self):
        text = self.render('--set', 'enabled=true')
        self.assertNotIn('kind: Ingress', text)
        self.assertIn('kind: Service\n', text)
        self.assertIn('ingress:\n    []', text)
        self.assertIn('egress: []', text)
        self.assertIn('automountServiceAccountToken: false', text)
        self.assertIn('runAsUser: 10001', text)
        self.assertIn('readOnlyRootFilesystem: true', text)
        self.assertIn('sha256:ed9210d6411d77ffceb70d94b964a3cb7d225983368bc25bebe01e995293dcc2', text)

    def test_protected_routes_and_secret_boundaries(self):
        text = self.render('--set', 'enabled=true', '--set', 'oidc.enabled=true',
            '--set', 'gateway.enabled=true', '--set', 'browserRoutes.enabled=true',
            '--set', 'authEgressCIDRs[0]=192.0.2.10/32', '--set',
            'gateway.image=example.invalid/reader@sha256:' + 'a'*64)
        self.assertIn('RUSTFS_IDENTITY_OPENID_REDIRECT_URI_DYNAMIC', text)
        self.assertIn('RUSTFS_IDENTITY_OPENID_CLAIM_NAME, value: rustfs_policy', text)
        self.assertNotIn('ROLE_POLICY', text)
        self.assertIn("RUSTFS_CONSOLE_CORS_ALLOWED_ORIGINS, value: 'https://rustfs.socrat.alchemmist.xyz'", text)
        self.assertIn("RUSTFS_CORS_ALLOWED_ORIGINS, value: ''", text)
        self.assertNotIn('kind: Secret', text)
        self.assertNotIn('kind: Role', text)
        self.assertIn('service: {name: rustfs-console-http', text)
        self.assertNotIn('service: {name: authentik-server', text)
        self.assertNotIn('path: /outpost.goauthentik.io/', text)
        self.assertIn('name: AUTH_URL', text)
        self.assertNotIn('nodePort:', text)
        self.assertNotIn('type: LoadBalancer', text)
        # Root is referenced by storage only; gateway has its isolated reader Secret.
        self.assertEqual(text.count('name: rustfs-root'), 2)
        self.assertEqual(text.count('name: rustfs-reader'), 2)
        self.assertNotIn('rustfs-writer', text)
        self.assertIn('path: /health/ready', text)

    def test_activation_guards(self):
        for values in [ ['--set','gateway.enabled=true'],
                        ['--set','browserRoutes.enabled=true'],
                        ['--set','oidc.enabled=true','--set','authEgressCIDRs[0]=0.0.0.0/0'] ]:
            result=subprocess.run(['helm','template','rustfs',str(ROOT/'charts/rustfs'),
                '--set','enabled=true',*values],capture_output=True)
            self.assertNotEqual(result.returncode,0)

    def test_manual_app(self):
        text = (ROOT / 'deploy/argocd/apps/rustfs.yaml').read_text()
        self.assertNotIn('automated:', text)


if __name__ == '__main__':
    unittest.main()
