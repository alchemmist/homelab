import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('capacity_trends', ROOT / 'scripts/otel-native-capacity-trends.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sample(timestamp, count, configuration='same', start=1):
    return {'observedAtUnix': timestamp, 'configurationSHA256': configuration, 'errors': [],
            'nativeCounters': {'loki': {'loki_distributor_bytes_received_total': count, 'process_start_time_seconds': start},
                               'tempo': {'tempo_distributor_bytes_received_total': count, 'process_start_time_seconds': start}},
            'storage': {'loki': {'allocatedBytes': 100}, 'tempo': {'allocatedBytes': 50}},
            'filesystem': {'availableBytes': 1000}}


class CapacityTrendTests(unittest.TestCase):
    def test_observed_interval_does_not_certify_retention(self):
        result = module().summarize([sample(1, 100), sample(301, 700)])
        self.assertEqual(result['nativeSignalTrends']['loki']['meanIngressBytesPerSecond'], 2)
        self.assertFalse(result['fullRetentionCapacityAcceptance'])
        self.assertFalse(result['minimum24hMeasurementReached'])

    def test_error_gap_config_and_process_resets_do_not_accumulate_old_time(self):
        for last in [sample(1301, 800), sample(601, 800, 'changed'), sample(601, 800, start=2), sample(601, 1)]:
            result = module().summarize([sample(1, 100), sample(301, 700), last])
            self.assertEqual(result['consecutiveMeasuredSeconds'], 0)
            self.assertEqual(len(result['resets']), 1)
        failed = copy.deepcopy(sample(301, 700))
        failed['errors'] = ['TimeoutError']
        result = module().summarize([sample(1, 100), failed, sample(601, 800)])
        self.assertEqual(result['consecutiveMeasuredSeconds'], 0)

    def test_clock_reversal_is_rejected(self):
        with self.assertRaises(ValueError):module().summarize([sample(2, 100), sample(1, 110)])
