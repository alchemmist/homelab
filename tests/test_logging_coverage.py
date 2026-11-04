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

    def test_kubernetes_requires_host_and_all_source_identities(self):
        source = {'kind': 'container', 'namespace': 'ns', 'pod': 'pod', 'container': 'app'}
        labels = {'host_name': 'node', 'k8s_namespace_name': 'ns', 'audit_pod': 'pod',
                  'audit_container': 'app', 'service_name': 'svc', 'severity': 'info'}
        good = {'labels': labels, 'count': 1}
        self.assertEqual(M.assess([source], [good], [good])[0]['status'], 'verified')
        for key in labels:
            with self.subTest(missing=key):
                incomplete = {'labels': {k: v for k, v in labels.items() if k != key}, 'count': 1}
                self.assertFalse(M.canonical_identity(source, incomplete['labels']))
                row = M.assess([source], [incomplete], [incomplete])[0]
                self.assertNotEqual(row['status'], 'verified')
                self.assertFalse(row['canonical'])
        incomplete = {'labels': {k: v for k, v in labels.items() if k != 'host_name'}, 'count': 1}
        row = M.assess([source], [good, incomplete], [good, incomplete])[0]
        self.assertEqual(row['status'], 'emits')
        self.assertFalse(row['canonical'])
        self.assertTrue(row['legacyObserved'])

    def test_host_inventory_does_not_infer_emission_from_installed_or_running(self):
        snapshots = [{'host': 'node', 'services': {
            'running.service': {'source': 'systemd', 'state': 'running', 'status': 'enabled'},
            'idle.service': {'source': 'systemd', 'state': 'stopped', 'status': 'disabled'},
            'oneshot.service': {'source': 'systemd', 'state': 'stopped', 'status': 'enabled'},
            'other': {'source': 'sysv', 'state': 'running'},
        }}]
        registry = M.host_registry(snapshots)
        self.assertEqual(len(registry), 3)
        self.assertTrue(all(r['exists'] is True and r['emission'] == 'unknown' for r in registry))
        rows = M.assess(M.inventory({}, {}, registry), [], [])
        self.assertTrue(all(r['status'] == 'unknown' and r['emits'] is None for r in rows))
        with self.assertRaises(ValueError):
            M.host_registry(snapshots + snapshots)

    def test_host_canonical_requires_matching_host_and_unit(self):
        source = {'kind': 'host', 'host': 'node', 'unit': 'unit.service'}
        labels = {'host_name': 'node', 'audit_unit': 'unit.service', 'service_name': 'app', 'severity': 'info'}
        self.assertTrue(M.canonical_identity(source, labels))
        for key in labels:
            self.assertFalse(M.canonical_identity(source, {k: v for k, v in labels.items() if k != key}))
