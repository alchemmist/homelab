"""Offline platform/tier guards; no network or production writes."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = list(yaml.safe_load_all((ROOT / 'deploy/storage/tiers/platform.yaml').read_text()))
CM = next(d for d in DOCS if d['kind'] == 'ConfigMap')


class StoragePlatformTest(unittest.TestCase):
    def test_explicit_dynamic_retained_local_tiers(self):
        for d in yaml.safe_load_all((ROOT / 'deploy/storage/tiers/classes.yaml').read_text()):
            self.assertEqual(d['provisioner'], 'rancher.io/local-path')
            self.assertEqual(d['reclaimPolicy'], 'Retain')
            self.assertEqual(d['volumeBindingMode'], 'WaitForFirstConsumer')
            self.assertEqual(d['metadata']['annotations']['defaultVolumeType'], 'local')
            self.assertEqual(d['metadata']['annotations']['storageclass.kubernetes.io/is-default-class'], 'false')
            self.assertEqual(d['allowedTopologies'][0]['matchLabelExpressions'][0]['values'], ['socrat-5'])

    def test_preserve_legacy_classes_and_default_node_mapping(self):
        c = json.loads(CM['data']['config.json'])
        self.assertEqual(c['nodePathMap'], [])
        for name in ['local-path', 'lms-db-retain', 'rustfs-retain', 'socrat-bot-retain', 'venice-browser-retain', 'pg-local-retain']:
            self.assertIn(name, c['storageClassConfigs'])
        local = c['storageClassConfigs']['local-path']['nodePathMap']
        self.assertIn({'node': 'socrat-5', 'paths': ['/mnt/files/homelab/volumes']}, local)
        for name in ['local-hdd', 'local-ssd']:
            self.assertIn({'node': 'DEFAULT_PATH_FOR_NON_LISTED_NODES', 'paths': []}, c['storageClassConfigs'][name]['nodePathMap'])

    def test_legacy_is_not_default(self):
        sc = next(d for d in DOCS if d['kind'] == 'StorageClass')
        self.assertEqual(sc['metadata']['annotations']['storageclass.kubernetes.io/is-default-class'], 'false')

    def run_setup(self, device, marker):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); parent = root / 'volumes'; parent.mkdir()
            (parent / '.homelab-filesystem-id').write_text(marker)
            tools = root / 'bin'; tools.mkdir()
            stat = tools / 'stat'; stat.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_DEVICE_ID"\n'); stat.chmod(0o755)
            script = CM['data']['setup'].replace('/mnt/files/homelab/volumes', str(parent))
            p = subprocess.run(['sh', '-c', script], env={**os.environ, 'VOL_DIR': str(parent / 'pvc-test'), 'TEST_DEVICE_ID': str(device), 'PATH': str(tools) + ':' + os.environ['PATH']}, capture_output=True, text=True)
            return p.returncode, (parent / 'pvc-test').exists()

    def test_missing_hdd_rejects_even_copied_identity_marker(self):
        code, created = self.run_setup(2049, '3ec3263e-32e3-4b38-84e6-17cd168244b9')
        self.assertNotEqual(code, 0); self.assertFalse(created)

    def test_wrong_marker_rejects_even_correct_device(self):
        code, created = self.run_setup(2065, 'wrong-filesystem')
        self.assertNotEqual(code, 0); self.assertFalse(created)

    def test_matching_identity_allows_directory_creation(self):
        code, created = self.run_setup(2065, '3ec3263e-32e3-4b38-84e6-17cd168244b9')
        self.assertEqual(code, 0); self.assertTrue(created)

    def test_teardown_guard_precedes_removal(self):
        text = CM['data']['teardown']
        self.assertLess(text.index('HDD_DEVICE_MISMATCH'), text.index('rm -rf'))

    def test_rancher_native_cache_can_reach_exact_node5_api(self):
        text = (ROOT / 'deploy/platform/rancher/public-entry/templates/observer-membership.yaml').read_text()
        self.assertIn('ipBlock: {cidr: 10.250.0.41/32}', text)
        self.assertIn('port: 6443', text)

    def test_archive_day2_refuses_unaccepted_mounts_and_never_restarts(self):
        text = (ROOT / 'ansible/playbooks/socrat-5-runtime-storage.yml').read_text()
        self.assertIn('Require already accepted archive binds', text)
        self.assertIn('/mnt/files/homelab/openhands-archives/cold-backups', text)
        self.assertNotIn('state: restarted', text)
        guard = (ROOT / 'ansible/files/socrat5-containerd-hdd-check').read_text()
        self.assertIn('/dev/sdb1[/homelab/openhands-archives/cold-backups]', guard)
        self.assertIn('/dev/sdb1[/homelab/openhands-archives/upgrade-backups]', guard)

    def test_inventory_matches_claim_namespace_not_only_name(self):
        spec = importlib.util.spec_from_file_location('audit_storage', ROOT / 'scripts/audit_storage.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        pv = {'metadata': {'name': 'fixture'}, 'spec': {'claimRef': {'namespace': 'a', 'name': 'data'}, 'capacity': {'storage': '1Gi'}, 'persistentVolumeReclaimPolicy': 'Retain'}}
        pods = [{'metadata': {'namespace': ns, 'name': ns}, 'spec': {'nodeName': 'socrat-5', 'volumes': [{'persistentVolumeClaim': {'claimName': 'data'}}]}} for ns in ['a', 'b']]
        self.assertEqual(module.inventory([pv], pods)[0]['consumers'], [{'pod': 'a', 'node': 'socrat-5'}])

    def test_storage_dashboard_keeps_missing_as_unknown(self):
        d = json.loads((ROOT / 'charts/monitoring-k3s/dashboards/storage.json').read_text())
        self.assertEqual(d['uid'], 'socrat-storage')
        for p in d['panels']:
            self.assertIn('{{mountpoint}}', p['targets'][0]['legendFormat'])
            self.assertNotIn('or vector(0)', p['targets'][0]['expr'])


if __name__ == '__main__':
    unittest.main()
