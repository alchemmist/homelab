import subprocess
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


class LokiMarkerScratchTests(unittest.TestCase):
    def test_loki_only_writable_bounded_scratch_preserves_security_and_data(self):
        rendered = "\n---\n".join(
            subprocess.check_output(
                ["helm", "template", name, str(ROOT / "charts" / name),
                 *(["--set-string", "storagePhase=local"] if name == "loki" else [])], text=True
            )
            for name in ("loki", "tempo")
        )
        deployments = {
            d["metadata"]["name"]: d
            for d in yaml.safe_load_all(rendered)
            if d and d["kind"] == "Deployment"
        }
        for name, d in deployments.items():
            spec = d["spec"]["template"]["spec"]
            c = spec["containers"][0]
            self.assertTrue(c["securityContext"]["readOnlyRootFilesystem"])
            self.assertFalse(c["securityContext"]["allowPrivilegeEscalation"])
            self.assertTrue(spec["securityContext"]["runAsNonRoot"])
            self.assertEqual(spec["securityContext"]["runAsUser"], 10001)
            mounts = {v["name"]: v for v in c["volumeMounts"]}
            volumes = {v["name"]: v for v in spec["volumes"]}
            self.assertEqual(mounts["data"]["mountPath"], "/var/lib/otel")
            self.assertTrue(mounts["tls"]["readOnly"])
            if name == "otel-loki":
                self.assertEqual(volumes["data"]["hostPath"]["path"], "/var/lib/private/homelab-otel-loki")
                self.assertEqual(mounts["marker-tmp"]["mountPath"], "/tmp")
                self.assertEqual(volumes["marker-tmp"]["emptyDir"], {"sizeLimit": "1Gi"})
            else:
                self.assertEqual(volumes["data"], {
                    "name": "data", "persistentVolumeClaim": {"claimName": yaml.safe_load((ROOT / "deploy/storage/tempo-drill/pvc.yaml").read_text())["metadata"]["name"]}
                })
                self.assertNotIn("marker-tmp", mounts)
                self.assertNotIn("marker-tmp", volumes)

    def test_loki_storage_phases(self):
        chart = ROOT / 'charts/loki'
        claim = yaml.safe_load((ROOT / 'deploy/storage/loki-drill/pvc.yaml').read_text())['metadata']['name']
        for phase in ('local', 'paused', 'shared', 'typo'):
            with self.subTest(phase=phase):
                result = subprocess.run(['helm', 'template', 'loki', str(chart), '-f', str(chart / 'alert-graphs.values.yaml'), '--set-string', f'storagePhase={phase}', '--show-only', 'templates/deployment.yaml'], text=True, capture_output=True)
                if phase == 'typo':
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('storagePhase must be', result.stderr)
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                dep = yaml.safe_load(result.stdout)['spec']
                self.assertEqual(dep['replicas'], 0 if phase == 'paused' else 1)
                self.assertEqual(dep['strategy']['type'], 'Recreate')
                pod = dep['template']['spec']
                data = next(v for v in pod['volumes'] if v['name'] == 'data')
                if phase != 'shared':
                    self.assertEqual(data['hostPath']['path'], '/var/lib/private/homelab-otel-loki')
                    self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname': 'socrat-1'})
                    continue
                self.assertEqual(data, {'name': 'data', 'persistentVolumeClaim': {'claimName': claim}})
                self.assertEqual(pod['nodeSelector'], {'kubernetes.io/os': 'linux'})
                affinity = pod['affinity']['nodeAffinity']
                terms = affinity['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
                self.assertEqual(len(terms), 1)
                self.assertIn({'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': ['socrat-0', 'socrat-1']}, terms[0]['matchExpressions'])
                self.assertIn({'weight': 100, 'preference': {'matchExpressions': [{'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': ['socrat-0']}]}}, affinity['preferredDuringSchedulingIgnoredDuringExecution'])
