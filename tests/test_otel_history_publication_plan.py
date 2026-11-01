import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
import stat

SPEC = importlib.util.spec_from_file_location('publication_plan', Path(__file__).resolve().parents[1] / 'scripts/otel-history-publication-plan.py')
PLAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLAN)
ORIGINAL = '01M66G9HT3YJ4W6TSADWG305M6'
CANDIDATE = '01M6C1A7HHG5S3K3F4WCXNR61C'
OTHER = '01M67BSZ1EMNPWMQ4SYBNEYJ8H'


class PublicationPlanTests(unittest.TestCase):
    def setUp(self):
        self.source = {'originalBlock': ORIGINAL, 'samples': 2, 'canonicalSHA256': 'a' * 64,
                       'fullOriginalCanonicalVerified': True, 'minTime': 100, 'maxTime': 200,
                       'externalLabels': {'prometheus': 'test'}}
        meta = {'ulid': CANDIDATE, 'minTime': 100, 'maxTime': 200, 'stats': {'numSamples': 2},
                'thanos': {'labels': {'prometheus': 'test'}, 'downsample': {'resolution': 0}}}
        self.stage = {'meta': meta, 'canonicalSHA256': 'a' * 64,
                      'result.json': {'verified': True, 'block': CANDIDATE, 'archiveSHA256Verified': True,
                                      'nativeIndexIssueVerificationPassed': True},
                      'durability.json': {'block': CANDIDATE, 'sameFilesystemRenameVerified': True}}
        self.live = {'meta': dict(copy.deepcopy(meta), ulid=ORIGINAL), 'deletionMarked': False}

    def plan(self, **kw):
        return PLAN.make_plan(kw.get('sources', [self.source]), kw.get('stages', [self.stage]),
                              kw.get('live', [self.live]), kw.get('subsets', []), kw.get('now', 1000), kw.get('observed_at', 999))

    def test_exact_candidate_is_never_execution_authorization(self):
        report = self.plan()
        self.assertFalse(report['productionPublicationApproved'])
        self.assertFalse(report['productionModified'])
        self.assertFalse(report['allCurrentHistoryVerified'])
        row = report['sourceRows'][0]
        self.assertFalse(row['publicationApproved'])
        self.assertEqual(row['action'], 'replace-exact-original-after-serving-barrier')
        self.assertTrue(row['blockers'])

    def test_counts_without_digest_never_bind_a_candidate(self):
        self.source['canonicalSHA256'] = 'b' * 64
        row = self.plan()['sourceRows'][0]
        self.assertIsNone(row['candidateBlock'])
        self.assertEqual(row['action'], 'await-full-roundtrip-and-native-stage')

    def test_absent_original_requires_compaction_reconciliation(self):
        row = self.plan(live=[])['sourceRows'][0]
        self.assertEqual(row['action'], 'reconcile-missing-original-before-publication')
        self.assertTrue(any('Original absent' in x for x in row['blockers']))

    def test_ambiguous_candidates_fail_closed(self):
        another = copy.deepcopy(self.stage)
        another['meta']['ulid'] = OTHER
        with self.assertRaises(ValueError):
            self.plan(stages=[self.stage, another])

    def test_duplicate_sources_and_live_identity_fail_closed(self):
        with self.assertRaises(ValueError):
            self.plan(sources=[self.source, self.source])
        with self.assertRaises(ValueError):
            self.plan(live=[self.live, self.live])

    def test_stale_and_future_observations_refused(self):
        for stamp in [0, 1031]:
            with self.assertRaises(ValueError):
                self.plan(observed_at=stamp)

    def test_wrong_receipt_identity_remains_blocked(self):
        self.stage['result.json']['block'] = OTHER
        self.assertIn('Missing or misbound native/durability receipt', self.plan()['sourceRows'][0]['blockers'])

    def test_native_anchor_does_not_replace_full_canonical_proof(self):
        self.source['fullOriginalCanonicalVerified'] = False
        self.assertIn('Full original canonical comparison not established', self.plan()['sourceRows'][0]['blockers'])

    def test_external_context_range_and_resolution_are_required(self):
        for mutate in [lambda m: m.update(maxTime=201),
                       lambda m: m['thanos'].update(labels={'prometheus': 'different'}),
                       lambda m: m['thanos']['downsample'].update(resolution=300000)]:
            stage = copy.deepcopy(self.stage)
            mutate(stage['meta'])
            self.assertIn('Native candidate range/resolution/external labels differ',
                          self.plan(stages=[stage])['sourceRows'][0]['blockers'])

    def test_subset_suppression_requires_full_content_and_bound_target(self):
        self.source['containedCandidate'] = CANDIDATE
        target = dict(self.source, originalBlock=OTHER, canonicalSHA256='b' * 64)
        proof = {'source': CANDIDATE, 'target': OTHER, 'sourceSamplesVerified': 2,
                 'targetCanonicalSHA256': 'b' * 64, 'fullSourceSubsetVerified': True,
                 'ordinaryLabelsTimestampsFloatBitsAndMultiplicityVerified': True}
        row = self.plan(sources=[self.source, target], subsets=[proof])['sourceRows'][0]
        self.assertEqual(row['action'], 'do-not-publish-contained-copy')
        proof['targetCanonicalSHA256'] = 'c' * 64
        row = self.plan(sources=[self.source, target], subsets=[proof])['sourceRows'][0]
        self.assertNotEqual(row['action'], 'do-not-publish-contained-copy')

    def test_ooo_overlap_is_not_automatically_removed_as_duplicate(self):
        self.source['outOfOrderCompanion'] = True
        another = copy.deepcopy(self.live)
        another['meta']['ulid'] = OTHER
        row = self.plan(live=[self.live, another])['sourceRows'][0]
        self.assertEqual(row['potentialLiveOverlap'], [ORIGINAL, OTHER])
        self.assertEqual(row['action'], 'replace-exact-original-after-serving-barrier')
        self.assertTrue(row['outOfOrderCompanion'])

    def test_changed_live_metadata_is_blocked(self):
        self.live['meta']['stats']['numSamples'] = 3
        self.assertIn('Original live semantic metadata changed; refresh canonical proof',
                      self.plan()['sourceRows'][0]['blockers'])

    def test_cli_creates_private_output_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'plan.json'
            args = ['plan', '--snapshot', 'metadata.json', '--tail-scope', 'scope.json', '--output', str(output)]
            with patch('sys.argv', args), patch.object(PLAN, 'build', return_value=self.plan()):
                PLAN.main()
                self.assertFalse(json.loads(output.read_text())['productionPublicationApproved'])
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
                before = output.read_bytes()
                with self.assertRaises(FileExistsError):
                    PLAN.main()
                self.assertEqual(output.read_bytes(), before)

    def test_unsafe_ids_and_malformed_digest_rejected(self):
        self.source['originalBlock'] = '../unsafe'
        with self.assertRaises(ValueError):
            self.plan()
        self.source['originalBlock'] = ORIGINAL
        self.source['canonicalSHA256'] = 'bad'
        with self.assertRaises(ValueError):
            self.plan()


if __name__ == '__main__':
    unittest.main()
