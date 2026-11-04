import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('coverage_check', Path(__file__).resolve().parents[1] / 'scripts/logging-coverage.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class CoverageTests(unittest.TestCase):
    def test_inventory_includes_all_container_types_and_empty_controllers(self):
        pod = {'metadata': {'namespace': 'ns', 'name': 'pod'}, 'spec': {k: [{'name': k}] for k in ('containers', 'initContainers', 'ephemeralContainers')}}
        sources = M.inventory({'items': [pod]}, {'items': [{'kind': 'Deployment', 'metadata': {'namespace': 'ns', 'name': 'zero'}}]}, [])
        self.assertEqual(len(sources), 4)
        self.assertEqual(M.assess(sources, [], [])[-1]['status'], 'exists')
        self.assertEqual(M.assess(sources, [], [])[0]['status'], 'unknown')

    def test_delivery_is_distinct_from_canonical_labels_and_silence(self):
        source = {'kind': 'host', 'host': 'node', 'unit': 'k3s.service', 'exists': True, 'emission': 'expected'}
        labels = {'host_name': 'node', 'service_name': 'k3s.service'}
        point = {'labels': labels, 'count': 1}
        self.assertEqual(M.assess([source], [point], [point])[0]['status'], 'emits')
        labels['severity'] = 'unknown'
        self.assertEqual(M.assess([source], [point], [point])[0]['status'], 'verified')
        self.assertEqual(M.assess([source], [], [point])[0]['status'], 'unknown')
        source['emission'] = 'silent'
        self.assertEqual(M.assess([source], [], [])[0]['status'], 'silent')

    def test_mixed_contract_is_not_verified(self):
        source = {'kind': 'host', 'host': 'n', 'unit': 'u'}
        points = [{'labels': {'host_name': 'n', 'service_name': 'u', **extra}, 'count': 1} for extra in ({}, {'severity': 'info'})]
        self.assertEqual(M.assess([source], points, points)[0]['status'], 'emits')

    def test_bounds_and_metadata_validation(self):
        for window in (600, 3600):
            query = M.query('{host_name!=""}', window)
            self.assertIn('count_over_time', query)
            self.assertIn('[' + str(window) + 's]', query)
        for point in ({'metric': {'body': 'secret'}, 'value': [0, '1']}, {'metric': {}, 'value': [0, 'NaN']}):
            with self.assertRaises(ValueError):
                M.validate({'status': 'success', 'data': {'resultType': 'vector', 'result': [point]}})
        with self.assertRaises(ValueError):
            M.validate({'status': 'success', 'warnings': ['partial'], 'data': {'resultType': 'vector', 'result': []}})

    def test_structured_host_unit_and_zero_counts(self):
        source = {'kind': 'host', 'host': 'n', 'unit': 'u'}
        point = {'labels': {'host_name': 'n', 'audit_unit': 'u', 'service_name': 'app', 'severity': 'warn'}, 'count': 0}
        self.assertEqual(M.assess([source], [point], [point])[0]['status'], 'unknown')
        point['count'] = 2
        self.assertEqual(M.assess([source], [point], [point])[0]['status'], 'verified')
