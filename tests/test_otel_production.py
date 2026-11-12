import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

class ProductionSafetyTests(unittest.TestCase):
    def test_host_token_roles_are_named_and_cannot_read_ca_private_key(self):
        boot = module('otel-production-bootstrap')
        resources = boot.resources({'requiredSecretKeys': []}, '10.43.1.2', {})
        roles = [r for r in resources if r['kind'] == 'Role' and r['metadata']['name'].startswith('otel-host-')]
        self.assertEqual(
            {r['metadata']['name'] for r in roles},
            {'otel-host-' + node for node in boot.NODES},
        )
        for role in roles:
            for rule in role['rules']:
                self.assertNotIn('*', rule['verbs'])
                self.assertNotIn('otel-root-ca', rule.get('resourceNames', []))
                if rule['resources'] == ['serviceaccounts/token']:
                    self.assertEqual(rule['resourceNames'], [role['metadata']['name']])

    def test_verified_private_wireguard_addresses_are_not_interchanged(self):
        boot = module('otel-production-bootstrap')
        self.assertEqual(boot.NODES['socrat-0'], '10.250.0.1')
        self.assertEqual(boot.NODES['socrat-2'], '10.250.0.2')

    def test_native_overlay_does_not_turn_on_legacy_scraping(self):
        import yaml
        values = yaml.safe_load((ROOT / 'deploy/monitoring/otel-production-values.yaml').read_text())
        spec = values['prometheus']['prometheusSpec']
        self.assertTrue(spec['listenLocal'])
        self.assertTrue(spec['enableOTLPReceiver'])
        self.assertEqual(spec['otlp']['translationStrategy'], 'NoTranslation')
        for key in ['serviceMonitorSelector', 'podMonitorSelector', 'scrapeConfigSelector', 'probeSelector']:
            self.assertEqual(spec[key]['matchLabels']['homelab.alchemmist.xyz/scrape-owner'], 'retired-legacy-prometheus')
        self.assertEqual(spec['evaluationInterval'], '5s')

