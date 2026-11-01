"""Offline deployment contracts; no credentials, cluster calls or fixture writes."""
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ArgoRefreshTests(unittest.TestCase):
    def test_short_tokens_with_refresh_and_native_tls(self):
        v = yaml.safe_load((ROOT/'deploy/argocd/values.yaml').read_text())
        oidc = yaml.safe_load(v['configs']['cm']['oidc.config'])
        self.assertIn('offline_access', oidc['requestedScopes'])
        self.assertEqual(oidc['refreshTokenThreshold'], '60s')
        self.assertEqual(v['configs']['cm']['users.session.duration'], '8h')
        self.assertFalse(v['configs']['params']['server.insecure'])
        a = v['server']['service']['annotations']
        self.assertEqual(a['traefik.ingress.kubernetes.io/service.serversscheme'], 'https')
        self.assertEqual(a['traefik.ingress.kubernetes.io/service.serverstransport'], 'argocd-argocd-verified-tls@kubernetescrd')
        source = (ROOT/'ansible/roles/argocd_oidc/files/configure.py').read_text()
        self.assertIn('required=["openid","profile","email","offline_access"]', source)
        self.assertIn('"access_token_validity":"minutes=5","refresh_token_validity":"hours=8"', source)

    def test_live_gitops_and_bootstrap_values_cannot_drift(self):
        bootstrap = yaml.safe_load((ROOT/'deploy/argocd/values.yaml').read_text())
        live = yaml.safe_load((ROOT/'deploy/platform/argo-cd/values.yaml').read_text())
        self.assertEqual(live, bootstrap)
        transport = yaml.safe_load((ROOT/'deploy/argocd/server-transport.yaml').read_text())
        self.assertEqual(live['extraObjects'], [transport])
        app = yaml.safe_load((ROOT/'deploy/argocd/apps/argo-cd.yaml').read_text())
        self.assertEqual(app['spec']['sources'][0]['helm']['valueFiles'], ['$values/deploy/platform/argo-cd/values.yaml'])

    def test_backend_certificate_verification_is_enabled(self):
        v = yaml.safe_load((ROOT/'deploy/argocd/server-transport.yaml').read_text())
        self.assertEqual(v['metadata']['namespace'], 'argocd')
        self.assertEqual(v['metadata']['labels']['homelab.alchemmist.xyz/edge-transport'], 'argocd')
        self.assertEqual(v['spec']['serverName'], 'argocd.socrat.alchemmist.xyz')
        self.assertFalse(v['spec']['insecureSkipVerify'])


if __name__ == '__main__':
    unittest.main()
