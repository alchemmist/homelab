import copy
import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('merge', ROOT / 'scripts/otel-logs-only-config.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ScopedRolloutTests(unittest.TestCase):
    def setUp(self):
        self.desired = yaml.safe_load((ROOT / 'deploy/monitoring/otel/agent.yaml').read_text())
        self.live = copy.deepcopy(self.desired)
        self.live['service']['pipelines']['logs']['exporters'] = ['otlp']
        del self.live['exporters']['otlp/logs']

    def test_preserves_metrics_receivers_and_checkpoints(self):
        self.live['receivers']['filelog']['start_at'] = 'beginning'
        self.live['receivers']['filelog']['include'] = ['/original/path']
        result = m.merge(self.live, self.desired)
        self.assertEqual(result['receivers'], self.live['receivers'])
        self.assertEqual(result['extensions'], self.live['extensions'])
        self.assertEqual(result['exporters']['otlp'], self.live['exporters']['otlp'])
        self.assertEqual(result['service']['pipelines']['metrics'], self.live['service']['pipelines']['metrics'])

    def test_shared_mutation_refused(self):
        self.live['processors']['memory_limiter']['limit_mib'] = 987
        with self.assertRaises(ValueError):
            m.merge(self.live, self.desired)

    def test_existing_log_endpoint_is_authoritative(self):
        self.live['exporters']['otlp/logs'] = copy.deepcopy(self.desired['exporters']['otlp/logs'])
        self.live['exporters']['otlp/logs']['endpoint'] = 'existing:4317'
        self.assertEqual(m.merge(self.live, self.desired)['exporters']['otlp/logs']['endpoint'], 'existing:4317')

    def test_pinned_counter_names_and_ambiguity(self):
        spec = importlib.util.spec_from_file_location('gate', ROOT / 'scripts/otel-logs-rollout-gate.py')
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        self.assertEqual(gate.total({'otelcol_exporter_sent_log_records{exporter="otlp/logs"}': 12}, 'otelcol_exporter_sent_log_records_total'), 12)
        self.assertEqual(gate.total({'otelcol_exporter_sent_log_records_total': 12}, 'otelcol_exporter_sent_log_records_total'), 12)
        with self.assertRaises(ValueError):
            gate.total({'otelcol_exporter_sent_log_records': 12, 'otelcol_exporter_sent_log_records_total': 12}, 'otelcol_exporter_sent_log_records_total')
