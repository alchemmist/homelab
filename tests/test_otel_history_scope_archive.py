import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scope_archive', ROOT / 'scripts/otel-history-verify-scope-archive.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
BLOCK = '01M66G9HT3YJ4W6TSADWG305M6'


class ScopeArchiveTests(unittest.TestCase):
    def fixture(self, root, unsafe=False):
        metadata = {'ulid': BLOCK, 'minTime': 0, 'maxTime': 10, 'stats': {'numSamples': 2},
                    'compaction': {'sources': ['source']}, 'thanos': {'labels': {'prometheus': 'original'}}}
        archive = root / 'legacy-tail.tar'
        with tarfile.open(archive, 'w') as tar:
            files = {BLOCK + '/meta.json': json.dumps(metadata).encode(), BLOCK + '/index': b'placeholder'}
            if unsafe:
                files['../escape'] = b'unsafe'
            for name, data in files.items():
                item = tarfile.TarInfo(name)
                item.size = len(data)
                tar.addfile(item, io.BytesIO(data))
        captured = {key: value for key, value in metadata.items() if key != 'thanos'}
        captured['externalLabels'] = metadata['thanos']['labels']
        receipt = {'originalFilesUnchanged': True, 'archiveBytes': archive.stat().st_size,
                   'archiveSHA256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'blocks': [captured], 'samples': 2}
        (root / 'capture.json').write_text(json.dumps(receipt))
        return receipt

    def test_transport_verification_never_claims_canonical_sample_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            verify.run(root)
            result = json.loads((root / 'verification.json').read_text())
            self.assertTrue(result['verified'])
            self.assertTrue(result['canonicalVerificationStillRequired'])
            self.assertFalse(result['productionModified'])
            self.assertTrue((root / 'legacy-tail.tar').exists())

    def test_bad_hash_preserves_failed_receipt_and_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = self.fixture(root)
            receipt['archiveSHA256'] = '0' * 64
            (root / 'capture.json').write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                verify.run(root)
            self.assertFalse(json.loads((root / 'verification.json').read_text())['verified'])
            self.assertTrue((root / 'legacy-tail.tar').exists())

    def test_unsafe_member_never_passes_even_with_matching_whole_archive_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root, unsafe=True)
            with self.assertRaises(ValueError):
                verify.run(root)
            self.assertFalse((root.parent / 'escape').exists())

    def test_roundtrip_payload_workspace_is_not_a_forbidden_production_output(self):
        import ast
        tree = ast.parse((ROOT / 'scripts/otel-history-current-roundtrip.py').read_text())
        workspace = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'WORK' for target in node.targets):
                workspace = node.value.args[0].value
        self.assertIsNotNone(workspace)
        self.assertTrue(workspace.startswith('/home/alchemmist/'))
        self.assertNotIn('/var/lib', workspace)
        source = (ROOT / 'scripts/otel-history-current-roundtrip.py').read_text()
        self.assertIn("exported = WORK / 'otlp'", source)
        self.assertIn("str(WORK / 'restored')", source)
