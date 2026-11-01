import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('history_migrate', ROOT / 'scripts/otel-history-migrate.py')
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def block(name, minimum, maximum, resolution=0, deleted=False):
    return {'ulid': name, 'minTime': minimum, 'maxTime': maximum,
            'resolution': resolution, 'deletionMarked': deleted}


class HistoryMigrationTests(unittest.TestCase):
    def test_contiguous_coverage_and_gaps(self):
        source = block('snapshot', 10, 30)
        self.assertTrue(MIGRATION.covered(source, [block('a', 0, 20), block('b', 20, 40)]))
        self.assertFalse(MIGRATION.covered(source, [block('a', 0, 19), block('b', 20, 40)]))
        self.assertFalse(MIGRATION.covered(source, [block('a', 20, 40)]))

    def test_deletion_marks_are_not_transferred_from_bucket_to_snapshot(self):
        receipt = {'reports': {
            'thanos-raw.tar.gz': {'blocks': [block('same', 0, 10, deleted=True)]},
            'prometheus-snapshot.tar.gz': {'blocks': [block('same', 0, 10)]}}}
        candidates, native = MIGRATION.classify_candidates(receipt)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['archive'], 'prometheus-snapshot.tar.gz')
        self.assertEqual(native[0]['reason'], 'bucket-deletion-mark-preserved')

    def test_downsamples_and_covered_snapshot_are_explicit_exceptions(self):
        receipt = {'reports': {
            'thanos-raw.tar.gz': {'blocks': [{**block('compacted', 0, 20), 'compactionSources': ['covered']}, block('downsampled', 0, 20, 300000)]},
            'prometheus-snapshot.tar.gz': {'blocks': [block('covered', 0, 10), block('head', 20, 30)]}}}
        before = copy.deepcopy(receipt)
        candidates, native = MIGRATION.classify_candidates(receipt)
        self.assertEqual([item['ulid'] for item in candidates], ['compacted', 'head'])
        self.assertEqual({item['reason'] for item in native}, {'downsampled-native', 'snapshot-range-covered-by-active-thanos-raw'})
        self.assertEqual(receipt, before)

    def test_timestamps_alone_do_not_prove_snapshot_duplicates(self):
        receipt = {'reports': {
            'thanos-raw.tar.gz': {'blocks': [block('unrelated', 0, 20)]},
            'prometheus-snapshot.tar.gz': {'blocks': [block('snapshot', 0, 10)]}}}
        candidates, native = MIGRATION.classify_candidates(receipt)
        self.assertEqual(len(candidates), 2)
        self.assertFalse(native)

    def test_private_exclusive_workspace_and_receipt_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'workspace'
            _, state = MIGRATION.prepare_workspace(path, {'cut': 'first'}, False)
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            self.assertEqual((path / 'state.json').stat().st_mode & 0o777, 0o600)
            self.assertFalse(state['productionModified'])
            self.assertEqual(MIGRATION.prepare_workspace(path, {'cut': 'first'}, True)[1], state)
            with self.assertRaises(ValueError):
                MIGRATION.prepare_workspace(path, {'cut': 'changed'}, True)
            with self.assertRaises(FileExistsError):
                MIGRATION.prepare_workspace(path, {'cut': 'first'}, False)

    def test_production_workspace_is_forbidden(self):
        for path in ['/var/lib/otel-test', '/srv/otel-test', '/etc/otel-test']:
            with self.assertRaises(ValueError):
                MIGRATION.prepare_workspace(Path(path), {}, False)

    def test_capacity_includes_twenty_percent_reserve(self):
        filesystem = SimpleNamespace(f_bavail=30, f_blocks=100, f_frsize=1)
        with mock.patch.object(MIGRATION.os, 'statvfs', return_value=filesystem):
            MIGRATION.require_disk(Path('/tmp'), 10)
            with self.assertRaises(ValueError):
                MIGRATION.require_disk(Path('/tmp'), 11)

    def test_old_staleness_refusal_is_not_treated_as_native_exception(self):
        process = SimpleNamespace(returncode=1, stderr='staleness markers require native preservation', stdout='')
        with mock.patch.object(MIGRATION.subprocess, 'run', return_value=process):
            with self.assertRaises(RuntimeError):
                MIGRATION.inventory_block(Path('/binary'), Path('/source'))

    def test_native_histograms_remain_explicit(self):
        process = SimpleNamespace(returncode=1, stderr='native histogram samples require native preservation', stdout='')
        with mock.patch.object(MIGRATION.subprocess, 'run', return_value=process):
            self.assertEqual(MIGRATION.inventory_block(Path('/binary'), Path('/source'))['status'], 'native-exception')

    def test_capabilities_are_not_a_canonical_roundtrip(self):
        report = {'samplesInChunks': 4, 'standardOTLPRepresentable': True, 'canonicalSamplesVerified': False}
        process = SimpleNamespace(returncode=0, stdout=json.dumps(report))
        with mock.patch.object(MIGRATION.subprocess, 'run', return_value=process):
            result = MIGRATION.inventory_block(Path('/binary'), Path('/source'))
        self.assertEqual(result['status'], 'representable')
        self.assertFalse(result['inventory']['canonicalSamplesVerified'])

    def test_unsupported_errors_do_not_become_native_success(self):
        process = SimpleNamespace(returncode=1, stderr='index checksum mismatch', stdout='')
        with mock.patch.object(MIGRATION.subprocess, 'run', return_value=process):
            with self.assertRaises(RuntimeError):
                MIGRATION.inventory_block(Path('/binary'), Path('/source'))

    def test_resume_verifies_finished_import_before_publishing_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exported, imported = root / 'exported', root / 'imported'
            exported.mkdir()
            imported.mkdir()
            manifest = {'sourceMeta': {'ulid': 'original'}, 'completeSourceBlock': True,
                        'samples': 4, 'canonicalSHA256': 'digest', 'staleMarkers': 2}
            (exported / 'manifest.json').write_text(json.dumps(manifest))
            restored = imported / ('0' * 26)
            restored.mkdir()
            (restored / 'meta.json').write_text('{}')
            with mock.patch.object(MIGRATION.subprocess, 'run') as run:
                verification = MIGRATION.finish_existing_import(Path('/binary'), exported, imported, {'ulid': 'original'})
            self.assertEqual(run.call_args.args[0][1], 'verify')
            self.assertTrue(verification['verified'])
            self.assertEqual(verification['staleMarkers'], 2)
            self.assertEqual(json.loads((imported / 'verification.json').read_text()), verification)

    def test_failed_resume_never_publishes_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exported, imported = root / 'exported', root / 'imported'
            exported.mkdir()
            imported.mkdir()
            (exported / 'manifest.json').write_text(json.dumps({'sourceMeta': {'ulid': 'original'}, 'completeSourceBlock': True}))
            restored = imported / ('0' * 26)
            restored.mkdir()
            (restored / 'meta.json').write_text('{}')
            with mock.patch.object(MIGRATION.subprocess, 'run', side_effect=RuntimeError('canonical mismatch')):
                with self.assertRaises(RuntimeError):
                    MIGRATION.finish_existing_import(Path('/binary'), exported, imported, {'ulid': 'original'})
            self.assertFalse((imported / 'verification.json').exists())


if __name__ == '__main__':
    unittest.main()
