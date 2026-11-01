import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('coverage', Path(__file__).resolve().parents[1] / 'scripts/otel-history-coverage.py')
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


def block(name, start=0, end=10, samples=100, ancestors=('a',), resolution=0, owner='original'):
    return {'meta': {'ulid': name, 'minTime': start, 'maxTime': end, 'stats': {'numSamples': samples},
                     'compaction': {'sources': list(ancestors)},
                     'thanos': {'labels': {'prometheus': owner}, 'downsample': {'resolution': resolution}}}}


class CoverageTests(unittest.TestCase):
    def test_exact_ancestry_does_not_approve_publication(self):
        result = coverage.reconcile([block('restored')], [block('original')])
        self.assertEqual(result['candidates'][0]['exactAncestryMatches'], ['original'])
        self.assertFalse(result['publicationApproved'])
        self.assertFalse(result['allCurrentHistoryVerified'])

    def test_containment_is_not_a_sample_subset_proof(self):
        result = coverage.classify(block('snapshot', ancestors=('snapshot',)), [block('compacted', end=20)])
        self.assertEqual(result['coveringRawBlocks'], ['compacted'])
        self.assertFalse(result['sampleCoverageVerified'])

    def test_downsample_and_changed_external_context_are_not_raw_replacements(self):
        result = coverage.classify(block('restored'), [block('downsample', resolution=300000), block('foreign', owner='foreign')])
        self.assertEqual(result['exactAncestryMatches'], [])
        self.assertEqual(result['coveringRawBlocks'], [])
        self.assertEqual(len(result['relatedRepresentations']), 1)

    def test_ambiguous_live_originals_are_rejected(self):
        with self.assertRaises(ValueError):
            coverage.reconcile([block('restored')], [block('one'), block('two')])


class PreservedTailTests(unittest.TestCase):
    def fixture(self):
        import copy
        normal = block('normal', samples=100, ancestors=('normal',))
        ooo = block('late', samples=2, ancestors=('late',))
        ooo['meta']['compaction']['hints'] = ['from-out-of-order']
        frozen = []
        for row in [normal, ooo]:
            meta = copy.deepcopy(row['meta'])
            meta['externalLabels'] = meta.pop('thanos')['labels']
            frozen.append(meta)
        capture = {'captured': True, 'blocks': frozen, 'originalFilesUnchanged': True, 'archiveSHA256': 'a' * 64, 'archiveBytes': 200}
        replica = {'verified': True, 'archiveSHA256': 'a' * 64, 'archiveBytes': 200, 'samples': 102, 'blockCount': 2}
        return capture, replica, [normal, ooo]

    def test_out_of_order_companion_is_never_dropped_as_an_overlap(self):
        capture, replica, current = self.fixture()
        result = coverage.reconcile_preserved_tail(capture, replica, current)
        self.assertEqual(len(result['capturedSources']), 2)
        self.assertTrue(result['capturedSources'][1]['outOfOrderCompanion'])
        self.assertFalse(result['capturedSources'][1]['fullCanonicalVerified'])
        self.assertFalse(result['publicationApproved'])

    def test_verified_but_different_replica_cannot_bind_originals(self):
        capture, replica, current = self.fixture()
        replica['archiveSHA256'] = 'b' * 64
        with self.assertRaises(ValueError):
            coverage.reconcile_preserved_tail(capture, replica, current)

    def test_missing_digest_on_both_receipts_is_not_equality(self):
        capture, replica, current = self.fixture()
        del capture['archiveSHA256']
        del replica['archiveSHA256']
        with self.assertRaises(ValueError):
            coverage.reconcile_preserved_tail(capture, replica, current)

    def test_changed_live_original_is_rejected(self):
        capture, replica, current = self.fixture()
        current[0]['meta']['stats']['numSamples'] += 1
        with self.assertRaises(ValueError):
            coverage.reconcile_preserved_tail(capture, replica, current)

    def test_new_compacted_ancestry_is_only_a_hint(self):
        capture, replica, current = self.fixture()
        result = coverage.reconcile_preserved_tail(capture, replica, [block('combined', ancestors=('normal', 'late'), samples=102)])
        self.assertFalse(result['capturedSources'][0]['unchangedLiveSemanticIdentity'])
        self.assertEqual(result['capturedSources'][0]['possibleCompactedCounterpartsRequiringFullSubsetProof'], ['combined'])
        self.assertFalse(result['allCurrentHistoryVerified'])
