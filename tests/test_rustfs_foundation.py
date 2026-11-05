"""Offline scaffold safety checks; not gateway/IAM/runtime acceptance."""
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
        self.assertNotIn('kind: Service\n', text)
        self.assertIn('ingress: []', text)
        self.assertIn('egress: []', text)
        self.assertIn('automountServiceAccountToken: false', text)
        self.assertIn('runAsUser: 10001', text)
        self.assertIn('readOnlyRootFilesystem: true', text)
        self.assertIn('sha256:ed9210d6411d77ffceb70d94b964a3cb7d225983368bc25bebe01e995293dcc2', text)

    def test_manual_app(self):
        text = (ROOT / 'deploy/argocd/apps/rustfs.yaml').read_text()
        self.assertNotIn('automated:', text)


if __name__ == '__main__':
    unittest.main()
