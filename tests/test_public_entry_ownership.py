"""Migration contracts: exact payload preservation and one owner per resource."""
import hashlib
import json
from pathlib import Path
import unittest
import yaml
from public_entry_contract import CHARTS, ROOT, render

class OwnershipTests(unittest.TestCase):
    def test_every_transferred_payload_is_identical_to_reviewed_pre_migration_render(self):
        fixture = json.loads((ROOT/'tests/fixtures/public-entry-handoff.json').read_text())
        actual = {}
        for owner in CHARTS:
            for resource in render(owner):
                key = '/'.join([resource['kind'], resource['metadata']['namespace'], resource['metadata']['name']])
                self.assertNotIn(key, actual, 'Multiple application owners: '+key)
                digest = hashlib.sha256(json.dumps(resource, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                actual[key] = {'owner': owner, 'sha256': digest}
        self.assertEqual(actual, fixture)

    def test_platform_extensions_belong_to_the_existing_application(self):
        for owner, chart in CHARTS.items():
            app = yaml.safe_load((ROOT/f'deploy/argocd/apps/{owner}.yaml').read_text())
            self.assertEqual(app['spec']['project'], 'default')
            sources = app['spec'].get('sources', [app['spec'].get('source', {})])
            self.assertEqual(len([s for s in sources if s.get('path') == chart]), 1)
            self.assertFalse(app['spec']['syncPolicy']['automated']['prune'])
            self.assertTrue(app['spec']['syncPolicy']['automated']['selfHeal'])

    def test_aggregate_chart_and_application_are_gone(self):
        self.assertFalse((ROOT/'charts/public-web-entry').exists())
        self.assertFalse((ROOT/'deploy/argocd/apps/public-web-entry.yaml').exists())
        for path in (ROOT/'deploy/argocd/apps').glob('*.yaml'):
            app = yaml.safe_load(path.read_text())
            self.assertNotEqual(app['metadata']['name'], 'public-web-entry')
            sources = app['spec'].get('sources', [app['spec'].get('source', {})])
            self.assertFalse(any(s.get('path') == 'charts/public-web-entry' for s in sources))
        litellm = yaml.safe_load((ROOT/'deploy/argocd/apps/litellm.yaml').read_text())
        self.assertIsNot(litellm['spec']['syncPolicy']['automated'].get('enabled'), False)
