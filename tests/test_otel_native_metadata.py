import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_metadata', ROOT / 'scripts/otel-history-native-metadata.py')
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


class NativeMetadataTests(unittest.TestCase):
    def test_exact_receipt_is_required(self):
        receipt = {'verified': True, 'nativePhysicalMetadataVerified': True, 'canonicalSHA256': 'a' * 64,
                   'samples': 123, 'productionModified': False, 'originalOutputModified': False}
        source = {'verification': {'canonicalSHA256': 'a' * 64, 'samples': 123}}
        metadata.check_receipt(receipt, source)
        for key, value in [('canonicalSHA256', 'b' * 64), ('samples', 122), ('verified', False),
                           ('nativePhysicalMetadataVerified', False), ('productionModified', True),
                           ('originalOutputModified', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                metadata.check_receipt({**receipt, key: value}, source)

    def test_independent_exporter_memory_is_not_hidden_in_agent_budget(self):
        policy = json.loads((ROOT / 'deploy/monitoring/otel-migration-policy.json').read_text())
        for node in policy['nodes'].values():
            self.assertEqual(node['components']['hostNodeExporter'], 64 * 1024 ** 2)
            self.assertEqual(node['components']['agent'], 256 * 1024 ** 2)

    def test_official_exporter_is_content_addressed(self):
        lock = json.loads((ROOT / 'deploy/monitoring/otel-node-exporter.lock.json').read_text())
        for key in ('runtimeIndexDigest', 'linuxAMD64ManifestDigest'):
            self.assertRegex(lock[key], r'^sha256:[a-f0-9]{64}$')
        self.assertRegex(lock['binarySHA256'], r'^[a-f0-9]{64}$')
        self.assertTrue(lock['exactRegularExecutableExtracted'])
        self.assertFalse(lock['productionOwnershipChanged'])

    def test_loopback_native_canary_has_cleanup_and_replay_guards(self):
        text = (ROOT / 'scripts/otel-host-source-canary.py').read_text()
        self.assertIn('Existing comparison output must not be reused', text)
        self.assertIn("result.get('probeReturnCode') != 0", text)
        self.assertIn("['systemctl', 'stop', unit]", text)
        self.assertIn('--web.listen-address=127.0.0.1:19100', text)
        self.assertIn('RuntimeMaxSec=180', text)
        self.assertIn('MemoryMax=67108864', text)
        self.assertNotIn('kubectl', text)
