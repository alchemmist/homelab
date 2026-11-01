import ast
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('tail_queue', Path(__file__).resolve().parents[1] / 'scripts/otel-history-tail-roundtrip.py')
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


class TailQueueTests(unittest.TestCase):
    def test_fast_profile_is_bounded_and_only_trusted_socrat0(self):
        fast = queue.execution_profile('socrat0-fast', 'socrat-0')
        self.assertEqual(fast['memoryBytes'], 9 * 1024**3)
        self.assertEqual(fast['gomaxprocs'], '16')
        self.assertEqual(fast['exportWorkers'], 50)
        self.assertEqual(fast['gomemlimit'], '6GiB')
        for node in ['socrat-1', 'socrat-2', 'socrat-3']:
            with self.assertRaises(ValueError):queue.execution_profile('socrat0-fast', node)
        self.assertEqual(queue.execution_profile('conservative', 'socrat-1')['cpus'], 2)

    def current(self):
        return {'success': True, 'actualNativeThanosQueryVerified': True, 'durableStagingVerified': True,
                'samples': 6383043932, 'canonicalSHA256': '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209'}

    def golden(self):
        # Exact published source/staged reference constants, not sampled anchors.
        pairs = [(4606695568, 'd49a8367a81cdd9dfd626fdf13eded48063abdb37289669d5572a8f8c3821b1f'),
                 (5955368159, '968bcb72e212318421325cf79f572066784c63433aa7d20ab60f0061ebbaaf43'),
                 (6137437488, 'aa43a0def61cd41d34336f6f68b2dae516aed8574d52b1513a6e82aa42280e81'),
                 (260844250, '9da8f16dc720a85adf1a3c37ddf9cc8956b2c0121aa5b3668671d735f65d2790'),
                 (261337432, '14ac7b9f5acb7a25cd869bcf07103d2ca03096ca6e67bb02e20b4fc2d8780856'),
                 (1043291602, '96b0b9f5f763ec154578de90b490a13683a81f42bae32c634118c8b356189acf')]
        return [{'success': True, 'samples': count, 'canonicalSHA256': digest,
                 'fullOriginalToRestoredCanonicalEqualityVerified': True,
                 'sourceArchiveSHA256': 'fc0f73919caa2615441e0053b632d6b48b087d5542bcc2c39c688267cea48632'} for count, digest in pairs]

    def test_all_canonical_native_durable_prerequisites_are_required(self):
        queue.prerequisites(self.current(), self.golden())
        for key in ['success', 'actualNativeThanosQueryVerified', 'durableStagingVerified']:
            current = self.current()
            current[key] = False
            with self.assertRaises(ValueError):
                queue.prerequisites(current, self.golden())

    def test_missing_or_wrong_original_digest_never_starts_queue(self):
        with self.assertRaises(ValueError):
            queue.prerequisites(self.current(), self.golden()[:-1])
        golden = self.golden()
        golden[0]['canonicalSHA256'] = '0' * 64
        with self.assertRaises(ValueError):
            queue.prerequisites(self.current(), golden)

    def test_repeated_golden_record_does_not_substitute_missing_original(self):
        golden = self.golden()
        golden[-1] = golden[0]
        with self.assertRaises(ValueError):
            queue.prerequisites(self.current(), golden)

    def test_source_id_scope_rejects_traversal_duplicates_and_unrelated_blocks(self):
        import inspect
        tree = ast.parse(inspect.getsource(queue.validate_source_names))
        expected = next(ast.literal_eval(node.value) for node in ast.walk(tree) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'expected' for target in node.targets))
        valid = [{'ulid': name} for name in sorted(expected)]
        queue.validate_source_names(valid)
        for bad in ['../../etc', valid[0]['ulid'], '01M00000000000000000000000']:
            changed = valid[:-1] + [{'ulid': bad}]
            with self.assertRaises(ValueError):
                queue.validate_source_names(changed)

    def test_resume_rejects_any_started_import_or_completed_blocks(self):
        progress = {'phase':'export','originalBlock':'01M66G9HT3YJ4W6TSADWG305M6','completedBlocks':0}
        previous = {'success':False,'blocks':[],'sourceArchiveSHA256':queue.ARCHIVE_PIN}
        queue.validate_export_resume(progress, previous)
        for key,value in [('phase','import'),('completedBlocks',1),('originalBlock','wrong')]:
            with self.assertRaises(ValueError):queue.validate_export_resume(dict(progress,**{key:value}),previous)
        with self.assertRaises(ValueError):queue.validate_export_resume(progress,dict(previous,success=True))

    def test_resume_preserves_valid_batches_and_quarantines_only_interrupted_last(self):
        import tempfile,json,gzip
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)/'base';work=Path(temporary)/'work';base.mkdir();work.mkdir()
            name='01M66G9HT3YJ4W6TSADWG305M6';root=work/name;root.mkdir();output=root/'otlp';output.mkdir()
            (base/'progress.json').write_text(json.dumps({'phase':'export','originalBlock':name,'completedBlocks':0}))
            (base/'result.json').write_text(json.dumps({'success':False,'blocks':[],'sourceArchiveSHA256':queue.ARCHIVE_PIN}))
            (root/'inventory.stdout').write_text(json.dumps({'samples':100,'canonicalSHA256':'a'*64}))
            (root/'export.stdout').write_text('');(root/'export.stderr').write_text('old log')
            valid=output/'000000.otlp.pb.gz';valid.write_bytes(gzip.compress(b'valid'))
            before=valid.read_bytes();(output/'000001.otlp.pb.gz').write_bytes(b'incomplete')
            with patch.object(queue,'BASE',base),patch.object(queue,'WORK',work):queue.prepare_export_resume()
            self.assertEqual(valid.read_bytes(),before)
            self.assertFalse((output/'000001.otlp.pb.gz').exists())
            self.assertEqual(len(list(root.glob('interrupted-transport-*/*.gz'))),1)
            self.assertEqual(len(list(base.glob('result.interrupted-export-*.json'))),1)

    def test_import_resume_preserves_old_native_work_and_archives_interrupted_receipt(self):
        import tempfile,json,hashlib
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)/'base';work=Path(temporary)/'work';base.mkdir();work.mkdir()
            name='01M66G9HT3YJ4W6TSADWG305M6';root=work/name;root.mkdir();(root/'otlp').mkdir();(root/'restored').mkdir()
            manifest=root/'otlp/manifest.json';manifest.write_text('sealed')
            (base/'progress.json').write_text(json.dumps({'phase':'import','originalBlock':name,'completedBlocks':0}))
            (base/'result.json').write_text(json.dumps({'success':False,'blocks':[],'sourceArchiveSHA256':queue.ARCHIVE_PIN}))
            proof={'verified':True,'version':1,'source':str(root/'otlp'),'samples':2500000,'shards':[{}],
                   'manifestSHA256':hashlib.sha256(b'sealed').hexdigest()}
            (base/'import-prefix-proof-v1.json').write_text(json.dumps(proof));(root/'import.stderr').write_text('old checkpoint')
            with patch.object(queue,'BASE',base),patch.object(queue,'WORK',work):queue.prepare_import_resume()
            self.assertTrue((root/'restored').is_dir())
            self.assertEqual(len(list(base.glob('result.interrupted-import-*.json'))),1)
            self.assertEqual(len(list(root.glob('import.interrupted-*.stderr'))),1)
