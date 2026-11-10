"""Read-only Helm render contracts for the scoped VPS CRD provider."""
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class EdgeCrdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = subprocess.check_output(['helm', 'template', 'traefik-edge', str(ROOT/'charts/traefik-edge'), '-n', 'traefik-edge'], text=True)
        cls.resources = [d for d in yaml.safe_load_all(output) if d]

    def test_provider_is_namespace_and_label_scoped(self):
        d = next(d for d in self.resources if d['kind']=='Deployment')
        args = d['spec']['template']['spec']['containers'][0]['args']
        self.assertIn('--providers.kubernetescrd=true', args)
        self.assertIn('--providers.kubernetescrd.namespaces=argocd', args)
        self.assertIn('--providers.kubernetescrd.labelselector=homelab.alchemmist.xyz/edge-transport=argocd', args)
        self.assertIn('--providers.kubernetescrd.allowcrossnamespace=false', args)
        self.assertIn('--providers.kubernetescrd.allowexternalnameservices=false', args)
        self.assertIn('--providers.kubernetescrd.disableclusterscoperesources=true', args)
        self.assertNotIn('--serverstransport.insecureskipverify=true', args)

    def test_vpn_middleware_uses_existing_discovery_without_wider_watches(self):
        m=next(d for d in self.resources if d['kind']=='Middleware' and d['metadata']['name']=='traefik-edge-vpn-msk-only')
        self.assertEqual(m['metadata']['namespace'],'argocd')
        self.assertEqual(m['spec']['ipAllowList']['sourceRange'],['10.251.4.1/32','10.250.0.40/32','127.0.0.1/32'])
        self.assertNotIn('ipStrategy',m['spec']['ipAllowList'])
        ingress=next(d for d in self.resources if d['kind']=='Ingress' and d['metadata']['name']=='traefik-edge-trojan-transit')
        self.assertEqual(ingress['metadata']['annotations']['traefik.ingress.kubernetes.io/router.middlewares'],'argocd-traefik-edge-vpn-msk-only@kubernetescrd')

    def test_only_trojan_path_is_gated_not_subscription_or_panel(self):
        ingress=next(d for d in self.resources if d['kind']=='Ingress' and d['metadata']['name']=='traefik-edge-vpn')
        paths=ingress['spec']['rules'][0]['http']['paths']
        self.assertEqual({p['backend']['service']['port']['number'] for p in paths},{18082,12096})
        self.assertNotIn('traefik.ingress.kubernetes.io/router.middlewares',ingress['metadata']['annotations'])
        transit=next(d for d in self.resources if d['kind']=='Ingress' and d['metadata']['name']=='traefik-edge-trojan-transit')
        paths=transit['spec']['rules'][0]['http']['paths']
        self.assertEqual(len(paths),1)
        self.assertEqual(paths[0]['backend']['service']['port']['number'],32087)
        self.assertEqual(paths[0]['pathType'],'Exact')

    def test_new_rbac_is_argocd_read_only_and_not_cluster_wide(self):
        roles = [d for d in self.resources if d['kind']=='Role' and d['metadata']['name']=='traefik-edge-crd']
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]['metadata']['namespace'], 'argocd')
        for rule in roles[0]['rules']:
            self.assertEqual(set(rule['verbs']), {'get','list','watch'})
            self.assertNotIn('*', rule['resources'])
        self.assertFalse(any(d['kind']=='ClusterRole' and d['metadata']['name'].endswith('-crd') for d in self.resources))


if __name__ == '__main__':
    unittest.main()
