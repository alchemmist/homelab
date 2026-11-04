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
        self.assertIn((10, '{severity="warn"}', 336), rules)
        self.assertIn('k8s.namespace.name, severity]', text)

    def test_service_beats_severity(self):
        self.policy['services'] = {'example': {'debug': 48, 'error': 336}}
        _, rules = m.rules(self.policy)
        self.assertIn((100, '{service_name="example",severity="debug"}', 48), rules)
        self.assertEqual(len({(p, s) for p, s, _ in rules}), len(rules))

    def test_reject_invalid_and_unmeasured_long_retention(self):
        for value in (0, 23, 8761, True, '72', 8760):
            with self.subTest(value=value):
                self.policy['severityHours']['error'] = value
                with self.assertRaises(ValueError):
                    m.rules(self.policy)

    def approval(self):
        return dict(measuredAt='2026-11-04', evidence='reviewed 7d report', approvedBy='operator',
                    budgetBytes=100000, projectedBytes=10000, measuredAllocatedBytes=1000,
                    filesystemCapacityBytes=1000000, filesystemAvailableBytes=800000,
                    otherWorkloadsReserveBytes=10000, transientReserveBytes=1000,
                    dailyGrowthUpperBytes=100, sampleSeconds=604800)

    def test_any_extension_needs_approval(self):
        for level in m.LEVELS - {'unknown'}:
            for value in (337, 720):
                with self.subTest(level=level, value=value):
                    policy = json.loads(m.POLICY.read_text())
                    policy['severityHours'][level] = value
                    with self.assertRaises(ValueError):
                        m.rules(policy)
        self.policy['services'] = {'example': {'debug': 337}}
        with self.assertRaises(ValueError):
            m.rules(self.policy)

    def test_capacity_gate(self):
        self.policy['capacityApproval'] = self.approval()
        self.policy['severityHours']['warn'] = 720
        m.rules(self.policy)
        for key, value in [('sampleSeconds', 120), ('projectedBytes', 7999),
                           ('budgetBytes', 900000), ('dailyGrowthUpperBytes', True),
                           ('approvedBy', ' '), ('filesystemAvailableBytes', 1000)]:
            with self.subTest(key=key):
                self.policy['capacityApproval'] = self.approval()
                self.policy['capacityApproval'][key] = value
                with self.assertRaises(ValueError):
                    m.rules(self.policy)

    def test_unknown_and_fallback_preserved(self):
        for field in ('fallback', 'unknown', 'service'):
            policy = json.loads(m.POLICY.read_text())
            if field == 'fallback':
                policy['fallbackHours'] = 168
            elif field == 'unknown':
                policy['severityHours']['unknown'] = 168
            else:
                policy['services'] = {'example': {'unknown': 168}}
            with self.assertRaises(ValueError):
                m.rules(policy)

    def test_reject_selector_injection(self):
        self.policy['services'] = {'bad"}': {'error': 336}}
        with self.assertRaises(ValueError):
            m.rules(self.policy)


if __name__ == '__main__':
    unittest.main()
