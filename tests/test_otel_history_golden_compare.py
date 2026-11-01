import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('golden_compare', Path(__file__).resolve().parents[1] / 'scripts/otel-history-golden-compare.py')
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)
BLOCK = '01M5P6GGQM3K9NAF43KP5JX3JW'


class GoldenComparisonTests(unittest.TestCase):
    def exercise(self, root, actual_hash='1' * 64, labels=None):
        remote = root / 'temporary-copies'
        source = remote / 'inputs' / BLOCK
        source.mkdir(parents=True)
        (remote / 'receipts').mkdir()
        original = root / 'preserved-original'
        original.write_text('never delete originals')
        binary = root / 'pinned-reader'
        binary.write_bytes(b'pinned offline reader')
        reference = {'samples': 1, 'canonicalSHA256': '1' * 64, 'minTime': 0, 'maxTime': 1, 'externalLabels': {'cluster': 'original'}}
        (remote / 'references.json').write_text(json.dumps({'references': {BLOCK: reference}, 'sourceArchiveSHA256': 'archive'}))
        (source / 'meta.json').write_text(json.dumps({'ulid': BLOCK, 'stats': {'numSamples': 1}, 'minTime': 0, 'maxTime': 1, 'thanos': {'labels': labels if labels is not None else reference['externalLabels']}}))
        completed = subprocess.CompletedProcess([], 0, json.dumps({'samples': 1, 'canonicalSHA256': actual_hash}), '')
        with patch.object(compare, 'REMOTE', remote), patch.object(compare, 'BINARY', binary), patch.object(compare, 'PIN', hashlib.sha256(binary.read_bytes()).hexdigest()), patch.object(compare.subprocess, 'run', return_value=completed) as reader, contextlib.redirect_stdout(io.StringIO()):
            if actual_hash != reference['canonicalSHA256'] or labels is not None:
                with self.assertRaises(ValueError):
                    compare.read(BLOCK)
                self.assertTrue(source.exists())
                self.assertFalse(json.loads((remote / 'receipts' / (BLOCK + '.json')).read_text())['success'])
                if labels is not None:
                    reader.assert_not_called()
            else:
                compare.read(BLOCK)
                self.assertFalse(source.exists())
                self.assertTrue(json.loads((remote / 'receipts' / (BLOCK + '.json')).read_text())['success'])
        self.assertTrue(original.exists())

    def test_exact_canonical_match_cleans_only_verified_transport_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.exercise(Path(temporary))

    def test_digest_mismatch_preserves_failed_copy_and_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.exercise(Path(temporary), actual_hash='2' * 64)

    def test_external_context_mismatch_fails_before_read_or_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.exercise(Path(temporary), labels={'cluster': 'wrong'})
