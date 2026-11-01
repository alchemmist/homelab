import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('log_matrix', ROOT / 'scripts/otel-log-delivery-matrix.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class LogDeliveryMatrixTests(unittest.TestCase):
    def test_only_bounded_native_count_queries_and_metadata(self):
        helper = module()
        self.assertTrue(all('count_over_time' in query and '[1h]' in query for query in helper.QUERIES.values()))
        document = {'status': 'success', 'data': {'resultType': 'vector', 'result': [
            {'metric': {'k8s_namespace_name': 'llm', 'audit_pod': 'open-webui-123', 'audit_container': 'open-webui'}, 'value': [1, '36']}]}}
        self.assertEqual(helper.select_counts(document), document['data']['result'])

    def test_partial_results_and_non_finite_counts_rejected(self):
        helper = module()
        for value in ['NaN', 'inf', '-1']:
            with self.assertRaises(ValueError):helper.select_counts({'status': 'success', 'data': {'resultType': 'vector', 'result': [{'metric': {}, 'value': [1, value]}]}})
        with self.assertRaises(ValueError):helper.select_counts({'status': 'success', 'warnings': ['partial'], 'data': {'resultType': 'vector'}})

    def test_unexpected_body_or_attribute_label_rejected(self):
        for labels in [{'body': 'private'}, {'service_name': 'https://user:password@example.invalid'}]:
            with self.assertRaises(ValueError):module().select_counts({'status': 'success', 'data': {'resultType': 'vector', 'result': [{'metric': labels, 'value': [1, '1']}]}})
