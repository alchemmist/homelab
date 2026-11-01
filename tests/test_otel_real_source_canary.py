import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('real_canary', ROOT / 'scripts/otel-real-source-canary.py')
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


class RealSourceCanaryTests(unittest.TestCase):
    def test_source_assets_and_discovery_use_private_files(self):
        original = {'authorization': {'credentials_file': '/etc/otel/source-auth/ns/name/key'},
                    'kubernetes_sd_configs': [{'role': 'endpoints'}], 'replacement': '$$1'}
        result = CANARY.rewrite_assets(original, {'/etc/otel/source-auth/ns/name/key': '/private/credential'}, Path('/private/kubeconfig'))
        self.assertEqual(result['authorization']['credentials_file'], '/private/credential')
        self.assertEqual(result['kubernetes_sd_configs'][0]['kubeconfig_file'], '/private/kubeconfig')
        self.assertEqual(result['replacement'], '$$1')
        self.assertNotIn('kubeconfig_file', original['kubernetes_sd_configs'][0])

    def test_existing_discovery_auth_is_never_silently_replaced(self):
        with self.assertRaises(ValueError):
            CANARY.rewrite_assets({'kubernetes_sd_configs': [{'api_server': 'https://other'}]}, {}, Path('/private/kubeconfig'))

    def test_expected_target_identity_covers_every_label(self):
        item = {'scrapePool': 'owned', 'health': 'up', 'labels': {'job': 'source', 'instance': 'node', 'namespace': 'test'}}
        expected = CANARY.expected_targets({'activeTargets': [item]}, {'owned'})
        self.assertEqual(expected, {CANARY.fingerprint({**item['labels'], '__name__': 'up'})})
        with self.assertRaises(ValueError):
            CANARY.expected_targets({'activeTargets': [item, item]}, {'owned'})
        with self.assertRaises(ValueError):
            CANARY.expected_targets({'activeTargets': [{**item, 'health': 'down'}]}, {'owned'})

    def test_cleanup_refuses_non_canary_workspaces(self):
        with self.assertRaises(ValueError):
            CANARY.cleanup_workspace(Path('/tmp/production-history'))
