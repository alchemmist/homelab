import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    path = ROOT / 'scripts' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ARCHIVE = load('otel-history-archive')
BACKUP = load('otel-history-backup')
ULID = '01ARZ3NDEKTSV4RRFFQ69G5FAV'


class HistoryArchiveTests(unittest.TestCase):
    def block(self, root, resolution=0):
        block = root / ULID
        (block / 'chunks').mkdir(parents=True)
        (block / 'meta.json').write_text(json.dumps({
            'ulid': ULID, 'minTime': 1000, 'maxTime': 2000,
            'thanos': {'downsample': {'resolution': resolution}},
        }))
        (block / 'index').write_bytes(b'index-payload')
        (block / 'chunks' / '000001').write_bytes(b'chunk-payload')
        return block

    def test_raw_and_downsampled_archives_preserve_resolution_and_marks(self):
        for resolution in (0, 300000, 3600000):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                block = self.block(root, resolution)
                (block / 'deletion-mark.json').write_text('{}')
                output = io.BytesIO()
                manifest = ARCHIVE.pack(root, output)
                output.seek(0)
                report = ARCHIVE.verify(output)
                self.assertTrue(report['verified'])
                self.assertEqual(report['fileCount'], 4)
                self.assertEqual(report['blocks'], manifest['blocks'])
                self.assertEqual(report['blocks'][0]['resolution'], resolution)
                self.assertTrue(report['blocks'][0]['deletionMarked'])
                self.assertTrue(block.exists())

    def test_corruption_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.block(root)
            output = io.BytesIO()
            ARCHIVE.pack(root, output)
            changed = output.getvalue().replace(b'chunk-payload', b'wrong-payload', 1)
            with self.assertRaises(ValueError):
                ARCHIVE.verify(io.BytesIO(changed))

    def test_compressed_archive_is_bound_to_source_sha256(self):
        import gzip
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.block(root)
            path = root / 'archive.tar.gz'
            with gzip.open(path, 'wb') as output:
                ARCHIVE.pack(root, output)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertTrue(ARCHIVE.verify_file(path, digest)['verified'])
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                ARCHIVE.verify_file(path, '0' * 64)

    def test_empty_shelf_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.BytesIO()
            ARCHIVE.pack(Path(directory), output)
            output.seek(0)
            self.assertEqual(ARCHIVE.verify(output)['blockCount'], 0)

    def test_live_wal_and_partial_uploads_are_not_silently_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ULID).mkdir()
            with self.assertRaisesRegex(ValueError, 'Incomplete block'):
                ARCHIVE.pack(root, io.BytesIO())

    def test_invalid_metadata_and_symlinks_are_rejected(self):
        for unsafe in ('symlink', 'metadata'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                block = self.block(root)
                if unsafe == 'symlink':
                    (block / 'secret').symlink_to('/etc/passwd')
                else:
                    (block / 'meta.json').write_text('{}')
                with self.assertRaises((ValueError, KeyError)):
                    ARCHIVE.pack(root, io.BytesIO())

    def test_manifest_and_path_traversal_are_required_checks(self):
        import tarfile
        for name in ('../escape', 'unregistered', ULID + '/index'):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode='w') as archive:
                info = tarfile.TarInfo(name)
                info.size = 1
                archive.addfile(info, io.BytesIO(b'x'))
            output.seek(0)
            with self.assertRaises(ValueError):
                ARCHIVE.verify(output)


class HistoryBackupRestorationTests(unittest.TestCase):
    def test_discovery_failure_restores_saved_controller_state(self):
        def get(host, resource, name):
            if resource == 'prometheus':
                return {'spec': {'enableAdminAPI': False}}
            if resource == 'cronjob':
                return {'spec': {'suspend': False}}
            return {'spec': {'replicas': 1}}

        def kube(host, *args, **kwargs):
            if args[:2] == ('get', 'pods'):
                raise RuntimeError('inspection failed')
            return '{}'

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'backup'
            with patch.object(BACKUP, 'get', side_effect=get), patch.object(BACKUP, 'kube', side_effect=kube) as kubectl, patch.object(BACKUP, 'patch') as changes, patch.object(BACKUP, 'wait_for'):
                with self.assertRaisesRegex(RuntimeError, 'inspection failed'):
                    BACKUP.backup('control', destination, 'replica')
                self.assertEqual(changes.call_count, 5)
                self.assertIn(('control', 'prometheus', BACKUP.PROMETHEUS, {'spec': {'enableAdminAPI': False}}), [call.args for call in changes.call_args_list])
                self.assertTrue(json.loads((destination / 'restoration.json').read_text())['restored'])
                self.assertTrue(any(call.args[1:3] == ('delete', 'configmap') for call in kubectl.call_args_list))

    def test_failed_restoration_keeps_the_lock_and_reports_failure(self):
        def get(host, resource, name):
            if resource == 'prometheus':
                return {'spec': {'enableAdminAPI': True}}
            if resource == 'cronjob':
                return {'spec': {'suspend': True}}
            return {'spec': {'replicas': 0}}

        def kube(host, *args, **kwargs):
            if args[:2] == ('get', 'pods'):
                raise RuntimeError('inspection failed')
            return '{}'

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'backup'
            with patch.object(BACKUP, 'get', side_effect=get), patch.object(BACKUP, 'kube', side_effect=kube) as kubectl, patch.object(BACKUP, 'patch', side_effect=RuntimeError('restore failed')), patch.object(BACKUP, 'wait_for'):
                with self.assertRaisesRegex(RuntimeError, 'RESTORATION INCOMPLETE'):
                    BACKUP.backup('control', destination, 'replica')
                self.assertFalse(json.loads((destination / 'restoration.json').read_text())['restored'])
                self.assertFalse(any(call.args[1:3] == ('delete', 'configmap') for call in kubectl.call_args_list))


if __name__ == '__main__':
    unittest.main()
