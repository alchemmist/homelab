"""Secret-free rendering/storage/backup contracts for worker5 migration."""
from pathlib import Path
import io
import tarfile
import os
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class Worker5MigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(subprocess.check_output(
            ['helm', 'template', 'n8n', str(ROOT / 'charts/n8n')], text=True)))

    def resource(self, kind, name):
        return next(d for d in self.docs if d and d['kind'] == kind and d['metadata']['name'] == name)

    def test_single_writer_local_retained_and_legacy_preserved(self):
        deployment = self.resource('Deployment', 'n8n')['spec']
        self.assertEqual(deployment['replicas'], 1)
        self.assertEqual(deployment['strategy']['type'], 'Recreate')
        spec = deployment['template']['spec']
        self.assertEqual(spec['nodeSelector']['kubernetes.io/hostname'], 'socrat-5')
        self.assertEqual(spec['volumes'][-1]['persistentVolumeClaim']['claimName'], 'n8n-socrat5')
        pv = self.resource('PersistentVolume', 'n8n-socrat5')['spec']
        self.assertEqual(pv['persistentVolumeReclaimPolicy'], 'Retain')
        self.assertEqual(pv['local']['path'], '/var/lib/rancher/k3s/storage/n8n-socrat5')
        self.resource('PersistentVolumeClaim', 'n8n')  # rollback PVC stays in desired state

    def test_backup_daily_readonly_no_api_access(self):
        cron = self.resource('CronJob', 'n8n-backup')['spec']
        self.assertEqual(cron['schedule'], '15 3 * * *')
        self.assertEqual(cron['timeZone'], 'Europe/Moscow')
        self.assertEqual(cron['concurrencyPolicy'], 'Forbid')
        spec = cron['jobTemplate']['spec']['template']['spec']
        self.assertFalse(spec['automountServiceAccountToken'])
        self.assertTrue(spec['containers'][0]['volumeMounts'][0]['readOnly'])
        self.assertEqual(spec['nodeSelector']['kubernetes.io/hostname'], 'socrat-5')

    def test_receiver_rejects_commands_and_uses_private_append_versions(self):
        receiver = ROOT / 'scripts/n8n/backup_receiver.py'
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, SSH_ORIGINAL_COMMAND='rm -rf /')
            p = subprocess.run(['python3', str(receiver)], env=env, input=b'not an archive', capture_output=True)
            self.assertNotEqual(p.returncode, 0)
            env['SSH_ORIGINAL_COMMAND'] = 'receive-n8n-backup'
            content = io.BytesIO()
            with tarfile.open(fileobj=content, mode='w:gz') as archive:
                for name in ['data/database.sqlite', 'manifest.json', 'encryption-key']:
                    member = tarfile.TarInfo(name)
                    member.size = 4
                    archive.addfile(member, io.BytesIO(b'test'))
            for _ in range(2):
                p = subprocess.run(['python3', str(receiver)], env=env, input=content.getvalue(), capture_output=True)
                self.assertEqual(p.returncode, 0, p.stderr)
            archives = list((Path(home) / 'backups/n8n').glob('*.tar.gz'))
            self.assertEqual(len(archives), 2)
            self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in archives))
            self.assertEqual(len(list(archives[0].parent.glob('*.sha256'))), 2)

    def test_only_named_local_claim_is_admitted(self):
        policy = next(yaml.safe_load_all((ROOT / 'deploy/admission/socrat5-local-storage.yaml').read_text()))
        expression = policy['spec']['validations'][0]['expression']
        self.assertIn("request.namespace == 'automation'", expression)
        self.assertIn("claimName == 'n8n-socrat5'", expression)
        self.assertNotIn('has(v.nfs)', expression)
        self.assertNotIn('has(v.csi)', expression)


if __name__ == '__main__':
    unittest.main()
