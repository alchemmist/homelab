import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_recovery', ROOT / 'scripts/otel-history-recover-source.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)
BLOCK = '01M61BHKG8EYTCRNMDHRYTBNKR'


class SourceRecoveryTests(unittest.TestCase):
    def archive(self, path, unsafe=False):
        entries = {'meta.json': json.dumps({'ulid': BLOCK}).encode(), 'index': b'index', 'chunks/000001': b'chunk'}
        with tarfile.open(path, 'w:gz') as tar:
            for name, content in entries.items():
                member = tarfile.TarInfo(BLOCK + '/' + name)
                member.size = len(content)
                tar.addfile(member, io.BytesIO(content))
            if unsafe:
                member = tarfile.TarInfo('../escape')
                member.size = 1
                tar.addfile(member, io.BytesIO(b'x'))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_whole_original_archive_is_hashed_before_source_is_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'original.tar.gz'
            digest = self.archive(archive)
            recovery.run(archive, BLOCK, digest, root / 'recovered')
            result = json.loads((root / 'recovered/result.json').read_text())
            self.assertTrue(result['verified'])
            self.assertEqual(result['compressedBytesRead'], archive.stat().st_size)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), digest)
            self.assertFalse(result['productionModified'])

    def test_bad_checksum_preserves_untrusted_staging_without_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'original.tar.gz'
            self.archive(archive)
            with self.assertRaises(ValueError):
                recovery.run(archive, BLOCK, '0' * 64, root / 'recovered')
            self.assertFalse(json.loads((root / 'recovered/result.json').read_text())['verified'])
            self.assertTrue((root / 'recovered/source' / BLOCK / 'index').exists())

    def test_traversal_is_rejected_even_outside_selected_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'original.tar.gz'
            digest = self.archive(archive, unsafe=True)
            with self.assertRaises(ValueError):
                recovery.run(archive, BLOCK, digest, root / 'recovered')
            self.assertFalse((root / 'escape').exists())
