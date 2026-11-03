import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReadBoundaryTests(unittest.TestCase):
    def test_only_known_read_limit_can_be_removed(self):
        repair = load('otel-store-read-boundary')
        arguments = ['store', '--max-time=-12h', '--consistency-delay=30m']
        self.assertEqual(repair.unclamped(arguments), ['store', '--consistency-delay=30m'])
        with self.assertRaises(ValueError):
            repair.unclamped(['store', '--max-time=-1d'])

    def test_boundary_gap_is_not_healthy_even_when_all_endpoints_are_up(self):
        soak = load('otel-production-soak')
        response = {'status': 'success', 'data': {'sidecar': [{'minTime': 100, 'lastError': None}],
                    'store': [{'name': 'thanos-store.example:10901', 'maxTime': 90, 'lastError': None}]}}
        with self.assertRaises(ValueError):
            soak.read_boundary(response)
        response['data']['store'][0]['maxTime'] = 110
        self.assertTrue(soak.read_boundary(response)['noAdvertisedBoundaryGap'])

    def test_configuration_epoch_changes_the_soak_fingerprint(self):
        soak = load('otel-production-soak')
        with tempfile.TemporaryDirectory() as temporary, patch.object(soak, 'ROOT', Path(temporary)):
            before = soak.configuration_sha256()
            (Path(temporary) / 'configuration-epoch.json').write_text('{"change":"raw-store-read-boundary"}')
            self.assertNotEqual(before, soak.configuration_sha256())

    def test_application_reader_has_no_ca_host_or_write_permissions(self):
        pki = load('otel-application-pki')
        resources = pki.resources()
        certificates = [item for item in resources if item['kind'] == 'Certificate']
        self.assertEqual(len(certificates), 5)
        for certificate in certificates:
            self.assertEqual(certificate['spec']['usages'], ['digital signature', 'client auth'])
            self.assertEqual(certificate['spec']['privateKey']['rotationPolicy'], 'Always')
        role = next(item for item in resources if item['kind'] == 'Role')
        rule = role['rules'][0]
        self.assertEqual(rule['verbs'], ['get'])
        self.assertNotIn('otel-root-ca', rule['resourceNames'])
        self.assertNotIn('otel-tls-socrat-0', rule['resourceNames'])
        self.assertEqual(len(rule['resourceNames']), 5)

    def test_rbac_evaluation_error_is_not_certified_as_denial(self):
        pki = load('otel-application-pki')
        with patch.object(pki.BOOTSTRAP, 'kube', return_value={'status': {'allowed': False, 'evaluationError': 'unavailable'}}):
            with self.assertRaises(ValueError):
                pki.assess('secrets', 'get', 'otel-root-ca')
