import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('query_audit', ROOT / 'scripts/otel-query-audit.py')
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class QueryAuditTests(unittest.TestCase):
    def test_numeric_literals_are_reviewed_without_rewriting(self):
        result = AUDIT.audit_expression('sum(foo_bucket{le="1.0"})')
        self.assertEqual(result['findings'][0]['otlpCandidate'], '1')
        self.assertFalse(AUDIT.audit_expression('sum(foo_bucket{le="+Inf"})')['findings'])
        self.assertEqual(AUDIT.otlp_number('1e-05'), '0.00001')

    def test_stock_compatible_regex_accepts_both_numeric_spellings(self):
        for number in ['1', '5', '30']:
            expression = 'sum(foo_bucket{le=~' + json.dumps(number + r'(\.0)?') + '})'
            self.assertFalse(AUDIT.audit_expression(expression)['findings'])
        self.assertTrue(AUDIT.audit_expression(r'foo_bucket{le=~"1\\.0"}')['findings'])
        self.assertFalse(AUDIT.compatible_numeric_regex(r'1000000(\.0)?'))

    def test_dynamic_values_and_other_labels_are_not_rewritten(self):
        result = AUDIT.audit_expression('foo{le="$boundary",instance="1.0"}')
        self.assertEqual(result['dynamicSelectorCount'], 1)
        self.assertFalse(result['findings'])
        self.assertEqual(AUDIT.audit_expression('foo{role="1.0"}')['selectorCount'], 0)

    def test_embedded_grafana_json_in_rendered_configmap_is_audited(self):
        document = {'kind': 'ConfigMap', 'data': {'dashboard.json': json.dumps({
            'panels': [{'targets': [{'expr': 'foo_bucket{le="1.0"}'}]}]})}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text(json.dumps(document))
            result = AUDIT.audit_files([path])
        self.assertEqual(result['expressionCount'], 1)
        self.assertEqual(result['reviewRequiredCount'], 1)
        self.assertFalse(result['queriesAutomaticallyRewritten'])
        self.assertNotIn('foo_bucket', json.dumps(result))
