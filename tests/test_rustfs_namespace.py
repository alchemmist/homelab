"""Offline migration gates; never claim runtime hostNetwork CNI acceptance."""
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from services.rustfs_gateway.gateway import Reader

ROOT = Path(__file__).resolve().parents[1]

class Namespace(unittest.TestCase):
    def render(self, namespace):
        return subprocess.check_output(['helm', 'template', 'rustfs', str(ROOT/'charts/rustfs'), '-n', 'rustfs', '-f', str(ROOT/'charts/rustfs/values-foundation-live.yaml'), '--set', 'browserRoutes.enabled=true', '--set', 'gateway.namespace='+namespace], text=True)

    def test_placements_and_isolation(self):
        for ns in ('rustfs', 'identity'):
            text = self.render(ns)
            docs = text.split('---')
            gateway = [d for d in docs if 'metadata: {name: rustfs-gateway' in d]
            self.assertEqual(len(gateway), 3)
            for d in gateway:
                self.assertIn('namespace: '+ns, d)
                self.assertNotIn('rustfs-root', d)
                self.assertNotIn('rustfs-oidc', d)
                self.assertNotIn('persistentVolumeClaim:', d)
            reader = next(d for d in docs if 'name: rustfs-evidence-browser' in d)
            self.assertIn('namespace: '+ns, reader)
            auth = next(d for d in docs if 'name: rustfs-authentik-browser' in d)
            self.assertIn('namespace: identity', auth)
            self.assertIn('namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: '+ns+'}}\n          podSelector: {matchLabels: {app: rustfs-gateway}}', text)
            self.assertIn('namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: rustfs}}\n          podSelector: {matchLabels: {app: rustfs}}', text)
            self.assertNotIn('0.0.0.0/0', text)
            storage = next(d for d in docs if 'kind: Deployment' in d and '  name: rustfs\n' in d)
            self.assertNotIn('namespace: identity', storage)
            self.assertIn('rustfs-root', storage)
        with self.assertRaises(subprocess.CalledProcessError):
            self.render('default')

    def test_fixed_destination(self):
        env = dict(AUTH_URL='https://spi-evidence.socrat.alchemmist.xyz/outpost.goauthentik.io/auth/nginx', S3_ACCESS_KEY='offline', S3_SECRET_KEY='offline')
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(Reader().s3, 'http://rustfs.rustfs.svc.cluster.local:9000')
            for endpoint in ('http://rustfs:9000', 'http://127.0.0.1:9000', 'https://public.example', 'http://rustfs.rustfs.svc.cluster.local:9000/evil'):
                with patch.dict(os.environ, S3_ENDPOINT=endpoint):
                    with self.assertRaises(ValueError): Reader()
