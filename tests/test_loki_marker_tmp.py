import subprocess
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

class LokiMarkerScratchTests(unittest.TestCase):
    def test_loki_only_writable_bounded_scratch_preserves_security_and_data(self):
        rendered = '\n---\n'.join(subprocess.check_output(['helm', 'template', name, str(ROOT/'charts'/name)], text=True) for name in ('loki', 'tempo'))
        deployments = {d['metadata']['name']: d for d in yaml.safe_load_all(rendered) if d and d['kind']=='Deployment'}
        for name, d in deployments.items():
            spec=d['spec']['template']['spec']; c=spec['containers'][0]
            self.assertTrue(c['securityContext']['readOnlyRootFilesystem'])
            self.assertFalse(c['securityContext']['allowPrivilegeEscalation'])
            self.assertTrue(spec['securityContext']['runAsNonRoot'])
            self.assertEqual(spec['securityContext']['runAsUser'],10001)
            mounts={v['name']:v for v in c['volumeMounts']}
            volumes={v['name']:v for v in spec['volumes']}
            self.assertEqual(mounts['data']['mountPath'],'/var/lib/otel')
            self.assertIn('hostPath',volumes['data'])
            self.assertTrue(mounts['tls']['readOnly'])
            if name=='otel-loki':
                self.assertEqual(mounts['marker-tmp']['mountPath'],'/tmp')
                self.assertEqual(volumes['marker-tmp']['emptyDir'],{'sizeLimit':'1Gi'})
            else:
                self.assertNotIn('marker-tmp',mounts)
                self.assertNotIn('marker-tmp',volumes)
