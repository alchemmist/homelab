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
        self.assertEqual(len(roles), 4)
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

    def test_risk_waiver_is_not_a_source_integrity_certificate(self):
        doc = json.loads((ROOT / 'deploy/monitoring/migration-evidence/operator-risk-acceptance-20261031.json').read_text())
        self.assertTrue(doc['operatorAuthorizedProductionCutover'])
        self.assertFalse(doc['sourceMemoryFailuresResolved'])
        self.assertFalse(doc['historySourceIntegrityVerified'])

    def test_missing_observation_time_cannot_be_counted_as_healthy_soak(self):
        soak = module('otel-production-soak')
        with tempfile.TemporaryDirectory() as directory:
            soak.ROOT = Path(directory)
            state = {'startedAt': 1, 'requiredSeconds': 259200, 'completed': False, 'checks': 10, 'failedChecks': 0,
                     'lastObservedAt': 1000, 'continuousHealthySince': 1}
            (soak.ROOT / 'state.json').write_text(json.dumps(state))
            with patch.object(soak.time, 'time', return_value=10000), patch.object(soak, 'query', side_effect=OSError('offline')):
                with self.assertRaises(SystemExit):
                    soak.run()
            observed = json.loads((soak.ROOT / 'state.json').read_text())
            self.assertFalse(observed['completed'])
            self.assertEqual(observed['measuredHealthySeconds'], 0)
            self.assertIsNone(observed['continuousHealthySince'])
            self.assertIn('production observation gap; healthy window reset', observed['lastErrors'])

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

    def test_soak_does_not_depend_on_its_own_previous_exit_state(self):
        source = (ROOT / 'scripts/otel-production-soak.py').read_text()
        self.assertIn('name!="homelab-otel-soak.service"', source)
        self.assertIn('name=~"homelab-otel.*"', source)
        self.assertNotIn('name!~"homelab-otel-soak.*"', source)
        self.assertIn("state['failedChecks'] += 1", source)
