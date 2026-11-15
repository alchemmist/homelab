"""Owner-approved static app placement: replace node2, retain two failure domains."""
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class StaticVMPlacementTests(unittest.TestCase):
    def render(self, name, *extra):
        output = subprocess.check_output([
            'helm', 'template', name, str(ROOT / 'charts' / name),
            '-f', str(ROOT / 'deploy' / name / 'values.yaml'), *extra,
        ], text=True)
        return next(d for d in yaml.safe_load_all(output)
                    if d and d.get('kind') == 'Deployment')

    def test_production_eligibility_and_two_failure_domains(self):
        for name, retained in [('blog', 'socrat-0'), ('socrat-home', 'socrat-1')]:
            with self.subTest(app=name):
                spec = self.render(name)['spec']
                self.assertEqual(spec['replicas'], 2)
                pod = spec['template']['spec']
                affinity = pod['affinity']
                self.assertEqual(affinity['nodeAffinity'], {
                    'requiredDuringSchedulingIgnoredDuringExecution': {
                        'nodeSelectorTerms': [{'matchExpressions': [{
                            'key': 'kubernetes.io/hostname', 'operator': 'In',
                            'values': [retained, 'socrat-5'],
                        }]}],
                    },
                })
                anti = affinity['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution']
                self.assertEqual(len(anti), 1)
                self.assertEqual(anti[0]['topologyKey'], 'kubernetes.io/hostname')
                self.assertEqual(anti[0]['labelSelector']['matchLabels'],
                                 spec['selector']['matchLabels'])
                self.assertNotIn('nodeName', pod)
                self.assertNotIn('nodeSelector', pod)

    def test_images_unchanged_and_no_persistent_data_added(self):
        for name in ['blog', 'socrat-home']:
            with self.subTest(app=name):
                values = yaml.safe_load((ROOT / 'deploy' / name / 'values.yaml').read_text())
                pod = self.render(name)['spec']['template']['spec']
                self.assertEqual(pod['containers'][0]['image'],
                                 values['image']['repository'] + '@' + values['image']['digest'])
                for volume in pod.get('volumes', []):
                    self.assertNotIn('persistentVolumeClaim', volume)
                    self.assertNotIn('hostPath', volume)

    def test_optional_scheduling_can_be_disabled(self):
        for name in ['blog', 'socrat-home']:
            with self.subTest(app=name):
                pod = self.render(name, '--set', 'nodeAffinity=null',
                                  '--set', 'podAntiAffinity.enabled=false')['spec']['template']['spec']
                self.assertNotIn('affinity', pod)


if __name__ == '__main__':
    unittest.main()
