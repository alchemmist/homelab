import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('native_capacity', ROOT / 'scripts/otel-native-capacity-observe.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeCapacityObserveTests(unittest.TestCase):
    def test_only_known_counters_are_aggregated_without_labels(self):
        text = '# TYPE sample counter\nloki_distributor_bytes_received_total{tenant="a"} 10\nloki_distributor_bytes_received_total{tenant="b"} 20\nunknown_metric{private="not-saved"} 99\n'
        self.assertEqual(load().counters(text), {'loki_distributor_bytes_received_total': 30.0})

    def test_invalid_negative_or_nonfinite_capacity_counter_fails_closed(self):
        for value in ['NaN', '+Inf', '-1']:
            with self.assertRaises(ValueError):load().counters('process_resident_memory_bytes ' + value)

    def test_metadata_inventory_deduplicates_hardlinks_and_does_not_follow_links(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'data'
            data.mkdir()
            (data / 'block').write_bytes(b'x' * 5000)
            os.link(data / 'block', data / 'alias')
            external = root / 'outside'
            external.mkdir()
            (external / 'must-not-count').write_bytes(b'x' * 9999)
            (data / 'link').symlink_to(external, target_is_directory=True)
            result = module.footprint(data)
            self.assertEqual(result['files'], 1)
            self.assertEqual(result['apparentBytes'], 5000)
            self.assertTrue(result['metadataOnly'])
