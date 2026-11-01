import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('metrics_smoke', ROOT / 'scripts/otel-metrics-smoke.py')
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def series(bound, value='3'):
    return {tuple(sorted({'__name__': 'smoke_duration_seconds_bucket', 'le': bound}.items())): value}


class MetricsSmokeTests(unittest.TestCase):
    def test_native_otlp_numeric_label_normalization_is_accepted(self):
        self.assertTrue(SMOKE.equivalent_series(series('1.0'), series('1')))
        self.assertTrue(SMOKE.equivalent_series(series('1e-05'), series('0.00001')))
        self.assertFalse(SMOKE.equivalent_series(series('1.0', '2'), series('1', '3')))
        self.assertFalse(SMOKE.equivalent_series(series('1.0'), series('2')))

    def test_semantic_view_never_merges_duplicate_series(self):
        data = {**series('1.0'), **series('1')}
        with self.assertRaises(ValueError):
            SMOKE.equivalent_series(data, data)

    def test_ordinary_string_labels_are_not_normalized(self):
        left = {(('__name__', 'smoke_value'), ('le', '1.0')): '3'}
        right = {(('__name__', 'smoke_value'), ('le', '1')): '3'}
        self.assertFalse(SMOKE.equivalent_series(left, right))

    def test_summary_quantile_normalization_preserves_other_labels(self):
        left = {(('__name__', 'smoke_summary'), ('quantile', '1.0'), ('region', 'one')): '3'}
        right = {(('__name__', 'smoke_summary'), ('quantile', '1'), ('region', 'one')): '3'}
        changed = {(('__name__', 'smoke_summary'), ('quantile', '1'), ('region', 'two')): '3'}
        self.assertTrue(SMOKE.equivalent_series(left, right))
        self.assertFalse(SMOKE.equivalent_series(left, changed))

    def test_dollar_literals_survive_the_intended_one_pass_resolution(self):
        original = {'replacement': '$1', 'regex': '(node)$', 'labels': ['${env:NOT_AN_ENV_REFERENCE}']}
        escaped = SMOKE.literal(original)
        self.assertEqual(escaped['replacement'], '$$1')
        self.assertEqual(escaped['regex'], '(node)$$')
        self.assertEqual(escaped['labels'], ['$${env:NOT_AN_ENV_REFERENCE}'])

    def test_fixture_can_remove_a_series_without_stopping_the_target(self):
        self.assertIn('smoke_value', SMOKE.metrics(17, True))
        removed = SMOKE.metrics(2, False)
        self.assertNotIn('smoke_value', removed)
        self.assertIn('smoke_requests_total 2', removed)
        self.assertIn('smoke_summary_count 3', removed)
