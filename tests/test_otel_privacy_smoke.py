import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('privacy_smoke', ROOT / 'scripts/otel-privacy-smoke.py')
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class PrivacySmokeTests(unittest.TestCase):
    def test_smoke_configuration_cannot_read_production_sources(self):
        source = {
            'receivers': {'prometheus': {'config': 'production'}, 'filelog': {'include': ['/var/log/pods/*']},
                          'otlp': {'protocols': {'http': {'endpoint': 'production:4318', 'tls': {'client_ca_file': 'validation-ca'}}}}},
            'processors': {'privacy': {}, 'unused': {}},
            'exporters': {'production': {'endpoint': 'production'}},
            'extensions': {'file_storage': {}, 'health_check': {}},
            'service': {'extensions': ['file_storage', 'health_check'], 'pipelines': {
                'logs': {'processors': ['privacy'], 'receivers': ['otlp'], 'exporters': ['production']},
                'metrics': {'receivers': ['prometheus']}}},
        }
        before = json.dumps(source, sort_keys=True)
        result = SMOKE.isolated_config(source, Path('/private/synthetic.json'))
        self.assertEqual(set(result['receivers']), {'otlp'})
        self.assertEqual(set(result['service']['pipelines']), {'logs'})
        self.assertEqual(set(result['exporters']), {'file'})
        self.assertEqual(result['receivers']['otlp']['protocols']['http']['endpoint'], '127.0.0.1:14318')
        self.assertEqual(result['receivers']['otlp']['protocols']['http']['tls']['client_ca_file'], 'validation-ca')
        self.assertEqual(json.dumps(source, sort_keys=True), before)

    def test_host_network_namespace_is_rejected_before_startup(self):
        with patch.object(SMOKE.os, 'readlink', return_value='net:[same]'):
            with self.assertRaisesRegex(ValueError, 'separate network namespace'):
                SMOKE.run(Path('/unused'), Path('/unused'), Path('/unused'), Path('/unused'))

    def test_otlp_partial_rejection_is_a_failure(self):
        with patch.object(SMOKE.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"partialSuccess":{"rejectedLogRecords":"1"}}')):
            with self.assertRaisesRegex(ValueError, 'rejected'):
                SMOKE.send(None, {})
