import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gitops_nodes', ROOT/'scripts/netbird-gitops-nodes.py')
gitops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gitops)


class GitOpsTests(unittest.TestCase):
    def values(self):return yaml.safe_load((ROOT/'deploy/netbird/values.yaml').read_text())

    def test_root_discovers_default_project_application_without_new_bootstrap(self):
        root = yaml.safe_load((ROOT/'deploy/argocd/root.yaml').read_text())
        app = yaml.safe_load((ROOT/'deploy/argocd/apps/netbird.yaml').read_text())
        self.assertEqual(root['spec']['source']['path'], 'deploy/argocd/apps')
        self.assertEqual(app['spec']['project'], 'default')
        self.assertEqual(app['spec']['source']['targetRevision'], 'main')
        self.assertEqual(app['spec']['source']['path'], 'charts/netbird')
        self.assertEqual(app['spec']['source']['helm']['parameters'], [])
        self.assertEqual(app['spec']['source']['helm']['valueFiles'], ['../../deploy/netbird/values.yaml'])
        self.assertEqual(app['spec']['syncPolicy']['automated'], {'prune': False, 'selfHeal': True})

    def test_real_helm_render_includes_complete_stack_without_secret_values(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(
            ['helm', 'template', 'netbird', str(ROOT/'charts/netbird'), '-f', str(ROOT/'deploy/netbird/values.yaml')], text=True)))
        self.assertEqual(len(docs), len(self.values()['resources']))
        deployments = [d for d in docs if d['kind'] == 'Deployment']
        self.assertEqual(len(deployments), 6+len(self.values()['nodes']))
        names = {d['metadata']['name'] for d in deployments}
        self.assertTrue({'dashboard', 'server', 'stun', 'netbird-edge-forwarder',
                         'netbird-relay-home', 'netbird-relay-vps'} <= names)
        self.assertFalse(any(d['kind'] in ['Secret', 'Job', 'ApplicationSet', 'AppProject'] for d in docs))
        for d in docs:
            if d['kind'] in ['Namespace', 'PersistentVolumeClaim']:
                self.assertEqual(d['metadata']['annotations']['argocd.argoproj.io/sync-options'], 'Prune=false,Delete=false')
            if d['kind'] != 'Deployment':continue
            for c in d['spec']['template']['spec']['containers']:
                self.assertIn('@sha256:', c['image'])
                for env in c.get('env', []):
                    self.assertNotEqual(env['name'], 'NB_SETUP_KEY')
                    if any(v in env['name'] for v in ['SECRET', 'TOKEN', 'PASSWORD']):
                        self.assertNotIn('value', env)
        dashboard = next(d for d in deployments if d['metadata']['name'] == 'dashboard')
        image = self.values()['image']
        self.assertEqual(dashboard['spec']['template']['spec']['containers'][0]['image'], image['repository']+'@'+image['digest'])

    def test_home_relay_admits_exact_vps_flannel_source_without_weakening_health(self):
        resources = self.values()['resources']
        policy = next(r for r in resources if r['kind'] == 'NetworkPolicy' and r['metadata']['name'] == 'netbird-relay-home')
        rule = policy['spec']['ingress'][0]
        cidrs = {source['ipBlock']['cidr'] for source in rule['from'] if 'ipBlock' in source}
        self.assertIn('10.42.0.0/32', cidrs)
        self.assertTrue(all(cidr.endswith('/32') for cidr in cidrs))
        self.assertEqual(rule['ports'], [{'port': 33080, 'protocol': 'TCP'}])
        deployment = next(r for r in resources if r['kind'] == 'Deployment' and r['metadata']['name'] == 'netbird-relay-home')
        container = deployment['spec']['template']['spec']['containers'][0]
        self.assertEqual(container['readinessProbe']['httpGet']['path'], '/health')
        self.assertEqual(container['readinessProbe']['httpGet']['port'], 9000)
        env = {e['name']: e for e in container['env']}
        self.assertIn('secretKeyRef', env['NB_AUTH_SECRET']['valueFrom'])
        self.assertEqual(env['NB_EXPOSED_ADDRESS']['value'], 'rels://netbird.socrat.alchemmist.xyz:443')

    def inventory(self, address='10.250.0.9'):
        return {'Socrat': {'hosts': ['socrat-4']}, '_meta': {'hostvars': {'socrat-4': {
            'wg_socrat_admin_clients': {'owner': {'address': '10.250.0.4'}},
            'wg_socrat_nodes': {'socrat-4': {'address': address}}}}}}

    def test_inventory_addition_only_generates_offline_git_resources(self):
        values = self.values(); original = copy.deepcopy(values['resources'])
        image = 'netbirdio/netbird:0.82.0@sha256:'+'a'*64
        self.assertEqual(gitops.desired(values, self.inventory(), image), ['socrat-4'])
        self.assertEqual(values['resources'][:len(original)], original)
        self.assertEqual(values['nodes']['socrat-4'], '10.250.0.9')
        self.assertEqual(len(values['resources']), len(original)+2)
        self.assertEqual(gitops.desired(values, self.inventory(), image), [])
        self.assertEqual(gitops.desired(values, {'Socrat': {'hosts': ['socrat-4']}, **{'_meta': self.inventory()['_meta']}}, image), [])
        with self.assertRaises(ValueError):gitops.desired(values, self.inventory('10.250.0.10'), image)
        values['resources'].pop()
        with self.assertRaises(ValueError):gitops.desired(values, self.inventory(), image)

    def test_controller_has_no_imperative_deployment_escape(self):
        runtime = object.__new__(gitops.node.Runtime)
        runtime.k = []
        with patch.object(gitops.node.subprocess, 'run') as run:
            for operation in ['create', 'apply', 'replace', 'patch', 'scale', 'run']:
                with self.subTest(operation=operation), self.assertRaises(ValueError):
                    runtime.kub([operation, '-f', '-'], {'kind': 'Deployment'})
            with self.assertRaises(ValueError):runtime.kub(['-n', gitops.node.NS, 'rollout', 'restart', 'deployment/a'])
            with self.assertRaises(ValueError):runtime.kub(['delete', 'pvc', 'anything'])
            run.assert_not_called()

    def test_old_control_plane_cli_cannot_apply(self):
        p = subprocess.run(['python3', str(ROOT/'scripts/netbird-deploy.py'), 'apply'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('exclusively managed by root -> netbird', p.stderr)
