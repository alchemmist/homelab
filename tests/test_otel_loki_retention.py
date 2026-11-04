import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('retention', ROOT / 'scripts/otel-loki-retention.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(m.POLICY.read_text())

    def test_copies_and_defaults(self):
        text = m.COPIES[0].read_text()
        self.assertEqual(text, m.COPIES[1].read_text())
        self.assertEqual(text, m.render(text, self.policy))
        fallback, rules = m.rules(self.policy)
        self.assertEqual(fallback, 336)
        self.assertIn((10, '{severity="unknown"}', 336), rules)
        self.assertIn((10, '{severity="debug"}', 72), rules)
        self.assertIn((10, '{severity="warn"}', 720), rules)
        self.assertIn('k8s.namespace.name, severity]', text)

    def test_service_beats_severity(self):
        self.policy['services'] = {'example': {'debug': 48, 'error': 720}}
        _, rules = m.rules(self.policy)
        self.assertIn((100, '{service_name="example",severity="debug"}', 48), rules)
        self.assertEqual(len({(p, s) for p, s, _ in rules}), len(rules))

    def test_reject_invalid_and_unmeasured_long_retention(self):
        for value in (0, 23, 8761, True, '72', 8760):
            with self.subTest(value=value):
                self.policy['severityHours']['error'] = value
                with self.assertRaises(ValueError):
                    m.rules(self.policy)

    def test_measured_365d_error_only(self):
        self.policy['capacityApproval'] = dict(measuredAt='2026-11-04', evidence='reviewed capacity report',
                                             budgetBytes=1000, projectedBytes=800, approvedBy='operator')
        self.policy['severityHours']['error'] = 8760
        m.rules(self.policy)
        self.policy['severityHours']['info'] = 8760
        with self.assertRaises(ValueError):
            m.rules(self.policy)

    def test_reject_selector_injection(self):
        self.policy['services'] = {'bad"}': {'error': 720}}
        with self.assertRaises(ValueError):
            m.rules(self.policy)


if __name__ == '__main__':
    unittest.main()
