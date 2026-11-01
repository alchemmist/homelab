import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('soak_sources', Path(__file__).resolve().parents[1] / 'scripts/otel-production-soak.py')
soak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)


def point(pod, value, job='cattle-monitoring-system/thanos'):
    return {'metric': {'job': job, 'pod': pod}, 'value': [1, str(value)]}


class SoakSourcesTests(unittest.TestCase):
    def test_only_deleted_pod_with_fresh_ready_same_replicaset_successor_is_retired(self):
        old = point('thanos-compactor-abc-old', 0)
        new = point('thanos-compactor-abc-new', 1)
        queried = []
        def lookup(expression):
            queried.append(expression)
            return [] if expression.startswith('kube_pod_info') else [{'value': [1, '1']}]
        active, retired = soak.effective_sources([old, new], lookup)
        self.assertEqual(active, [new])
        self.assertEqual(len(retired), 1)
        self.assertIn('owner_is_controller="true"', queried[-1])
        self.assertIn('kube_pod_status_ready', queried[-1])
        self.assertIn('timestamp(', queried[-1])

    def test_live_old_pod_is_not_hidden(self):
        points = [point('thanos-compactor-abc-old', 0), point('thanos-compactor-abc-new', 1)]
        active, retired = soak.effective_sources(points, lambda expression: [] if expression.startswith('kube_pod_deletion_timestamp') else [{'value': [1, '1']}])
        self.assertEqual(active, points)
        self.assertFalse(retired)

    def test_terminating_old_pod_needs_ready_singleton_successor(self):
        points = [point('thanos-compactor-abc-old', 0), point('thanos-compactor-abc-new', 1)]
        expressions = []
        def lookup(expression):
            expressions.append(expression)
            return [{'value': [1, '1']}]
        active, retired = soak.effective_sources(points, lookup)
        self.assertEqual(active, [points[1]])
        self.assertEqual(len(retired), 1)
        self.assertTrue(any('kube_pod_deletion_timestamp' in x for x in expressions))
        self.assertIn('kube_replicaset_spec_replicas', expressions[-1])

    def test_missing_or_unready_or_different_replicaset_successor_still_fails(self):
        old = point('thanos-compactor-abc-old', 0)
        for points in [[old], [old, point('thanos-compactor-abc-new', 0)], [old, point('thanos-compactor-def-new', 1)], [old, point('thanos-compactor-abc-new', 1)]]:
            active, retired = soak.effective_sources(points, lambda expression: [])
            self.assertIn(old, active)
            self.assertFalse(retired)

    def test_unrelated_failures_are_never_filtered(self):
        points = [point('api-abc-old', 0), point('thanos-compactor-abc-old', 0, job='foreign')]
        def lookup(expression):
            self.fail('Unrelated unhealthy targets must not be filtered')
        self.assertEqual(soak.effective_sources(points, lookup), (points, []))
