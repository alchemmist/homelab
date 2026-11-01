import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('storage_capacity', ROOT / 'scripts/otel-storage-capacity-observe.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class StorageCapacityTests(unittest.TestCase):
    def test_numeric_metadata_only_no_chunks_index_or_labels_read(self):
        helper = module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            block = root / '01M66BZJJH7AX3HTZFRZD02SXP'
            block.mkdir()
            meta = {'minTime': 1, 'maxTime': 10, 'stats': {'numSamples': 6383043932, 'numSeries': 7, 'numChunks': 9},
                    'thanos': {'labels': {'private': 'SYNTHETIC_PRIVATE_LABEL'}, 'downsample': {'resolution': 0}}}
            (block / 'meta.json').write_text(json.dumps(meta))
            (block / 'index').write_bytes(b'NEVER_READ_PAYLOAD')
            original = Path.read_text
            def read(path, *args, **kwargs):
                self.assertEqual(path.name, 'meta.json')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'read_text', read):result = helper.inventory(root)
            self.assertEqual(result['nativeBlocks'][0]['numSamples'], 6383043932)
            self.assertNotIn('SYNTHETIC_PRIVATE_LABEL', json.dumps(result))
            self.assertFalse(result['payloadsOrLabelsRead'])

    def test_symlinks_excluded_hardlinks_deduplicated_wal_measured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'wal').mkdir()
            (root / 'wal/segment').write_bytes(b'1' * 8192)
            os.link(root / 'wal/segment', root / 'duplicate')
            (root / 'link').symlink_to(root / 'wal', target_is_directory=True)
            result = module().inventory(root)
            self.assertEqual(result['files'], 1)
            self.assertGreater(result['allocatedBytes'], 0)
            self.assertEqual(result['walAndHeadAllocatedBytes']['wal'], result['allocatedBytes'])

    def test_maintained_memory_gate_never_evicts_workloads_and_pauses_only_owned_observer(self):
        text = (ROOT / 'ansible/playbooks/otel-storage-capacity.yml').read_text()
        self.assertIn('32 if inventory_hostname == "socrat-2" else 128', text)
        self.assertIn('MemTotal / 5', text)
        self.assertIn("timer='homelab-otel-storage-capacity.timer'", text)
        self.assertIn("(timer,['stop','disable']),(service,['stop'])", text)
        self.assertNotIn('kubectl delete', text)
        self.assertNotIn('kubectl drain', text)

    def test_bounded_file_budget_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'file').write_bytes(b'x')
            with self.assertRaises(ValueError):module().inventory(root, limit=0)
