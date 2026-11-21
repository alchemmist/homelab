"""Offline safety contracts for static storage tiers and filesystem monitoring."""
import importlib.util
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('audit_storage', ROOT / 'scripts/audit_storage.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class StorageTiersTest(unittest.TestCase):
    def test_cold_migration_plan_keeps_state_and_requires_approval(self):
        spec = importlib.util.spec_from_file_location('migration_plan', ROOT / 'scripts/check_storage_migration_plan.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plan = json.loads((ROOT / 'deploy/storage/plans/socrat5-hdd-first.json').read_text())
        module.validate(plan)
        plan['runtime']['delete_source_automatically'] = True
        with self.assertRaises(AssertionError):
            module.validate(plan)

    def test_classes_are_explicit_static_and_retained(self):
        docs = list(yaml.safe_load_all((ROOT / 'deploy/storage/tiers/classes.yaml').read_text()))
        self.assertEqual({d['metadata']['name'] for d in docs}, {'local-ssd', 'local-hdd'})
        for d in docs:
            self.assertEqual(d['provisioner'], 'kubernetes.io/no-provisioner')
            self.assertEqual(d['reclaimPolicy'], 'Retain')
            self.assertEqual(d['volumeBindingMode'], 'WaitForFirstConsumer')
            self.assertEqual(d['metadata']['annotations']['storageclass.kubernetes.io/is-default-class'], 'false')

    def test_inventory_joins_namespace_not_only_claim_name(self):
        pv = {'metadata': {'name': 'x'}, 'spec': {'claimRef': {'namespace': 'a', 'name': 'data'},
              'capacity': {'storage': '1Gi'}, 'persistentVolumeReclaimPolicy': 'Retain'}}
        pods = [{'metadata': {'namespace': ns, 'name': ns}, 'spec': {'nodeName': 'socrat-5',
                 'volumes': [{'persistentVolumeClaim': {'claimName': 'data'}}]}} for ns in ['a', 'b']]
        rows = audit.inventory([pv], pods)
        self.assertEqual(rows[0]['consumers'], [{'pod': 'a', 'node': 'socrat-5'}])

    def test_storage_dashboard_preserves_mount_identity(self):
        d = json.loads((ROOT / 'charts/monitoring-k3s/dashboards/storage.json').read_text())
        self.assertEqual(d['uid'], 'socrat-storage')
        self.assertEqual(len({p['id'] for p in d['panels']}), len(d['panels']))
        for p in d['panels']:
            self.assertIn('{{mountpoint}}', p['targets'][0]['legendFormat'])
            self.assertNotIn('or vector(0)', p['targets'][0]['expr'])
            self.assertFalse(p['fieldConfig']['defaults']['custom']['spanNulls'])

    def test_root_tv_scope_not_silently_expanded(self):
        d = json.loads((ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json').read_text())
        p = next(p for p in d['panels'] if p['id'] == 23)
        self.assertIn('system', p['title'])
        for t in p['targets']:
            self.assertIn('mountpoint="/"', t['expr'])

    def test_rules_cover_missing_mount_bytes_and_inodes(self):
        text = (ROOT / 'charts/monitoring-k3s/templates/storage-rules.yaml').read_text()
        self.assertIn('absent_over_time', text)
        self.assertIn('device="/dev/sdb1"', text)
        self.assertIn('node_filesystem_avail_bytes', text)
        self.assertIn('node_filesystem_files_free', text)

    def test_no_existing_storage_adoption(self):
        docs = list(yaml.safe_load_all((ROOT / 'deploy/storage/tiers/classes.yaml').read_text()))
        self.assertTrue(all(d['kind'] == 'StorageClass' for d in docs))
        self.assertNotIn('local-path', [d['metadata']['name'] for d in docs])


if __name__ == '__main__':
    unittest.main()
