from pathlib import Path
import shutil
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class WikiSocrat0PlacementTest(unittest.TestCase):
    def test_retained_volume_matches_values_and_existing_directory(self):
        values = yaml.safe_load((ROOT / 'deploy/wiki-runtime/values.yaml').read_text())
        pv, pvc = list(yaml.safe_load_all((ROOT / 'ansible/files/wiki-runtime-storage-socrat-0.yaml').read_text()))
        self.assertEqual(values['persistence']['existingClaim'], pvc['metadata']['name'])
        self.assertEqual(pvc['spec']['volumeName'], pv['metadata']['name'])
        self.assertEqual(pv['spec']['persistentVolumeReclaimPolicy'], 'Retain')
        self.assertEqual(pv['spec']['hostPath']['type'], 'Directory')
        self.assertEqual(pv['spec']['nodeAffinity']['required']['nodeSelectorTerms'][0]['matchExpressions'][0]['values'], ['socrat-0'])
        self.assertEqual(values['nodeSelector'], {'kubernetes.io/hostname': 'socrat-0'})

    @unittest.skipUnless(shutil.which('helm'), 'helm is required')
    def test_rendered_deployment_has_one_writer_and_new_claim(self):
        result = subprocess.check_output([
            'helm', 'template', 'wiki-runtime', str(ROOT / 'deploy/wiki-runtime/chart'),
            '-n', 'wiki', '-f', str(ROOT / 'deploy/wiki-runtime/values.yaml'),
        ], text=True)
        deployment = next(item for item in yaml.safe_load_all(result) if item and item['kind'] == 'Deployment')
        self.assertEqual(deployment['spec']['replicas'], 1)
        self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
        pod = deployment['spec']['template']['spec']
        self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname': 'socrat-0'})
        data = next(volume for volume in pod['volumes'] if volume['name'] == 'data')
        self.assertEqual(data['persistentVolumeClaim']['claimName'], 'wiki-runtime-data-socrat-0')


if __name__ == '__main__':
    unittest.main()
