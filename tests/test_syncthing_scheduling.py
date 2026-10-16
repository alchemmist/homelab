import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

try:
    import yaml
except ImportError:
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get('HELM_BIN') or shutil.which('helm')


@unittest.skipUnless(HELM and yaml, 'Helm and PyYAML are required')
class SyncthingSchedulingTests(unittest.TestCase):
    def render(self, overrides):
        with tempfile.TemporaryDirectory() as directory:
            values = Path(directory) / 'values.json'
            values.write_text(json.dumps(overrides))
            return subprocess.run(
                [HELM, 'template', 'syncthing', str(ROOT / 'charts/syncthing'), '-f', str(values)],
                capture_output=True, text=True, timeout=30,
            )

    def resources(self, overrides):
        result = self.render(overrides)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [item for item in yaml.safe_load_all(result.stdout) if item]

    def test_only_nodes_with_sidecar_configuration_are_eligible(self):
        for overrides in [{}, {'privateGui': {'nodes': [
            {'nodeName': 'socrat-7', 'host': '7.socrat.example.org', 'wgIP': '10.250.0.7'}
        ]}}]:
            with self.subTest(overrides=overrides):
                resources = self.resources(overrides)
                pod = next(item for item in resources if item['kind'] == 'DaemonSet')['spec']['template']['spec']
                configuration = next(item for item in resources if item['kind'] == 'ConfigMap')['data']
                terms = pod['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
                eligible = set()
                for term in terms:
                    selector = term['matchFields'][0]
                    self.assertEqual(selector['key'], 'metadata.name')
                    self.assertEqual(selector['operator'], 'In')
                    self.assertEqual(len(selector['values']), 1)
                    eligible.update(selector['values'])
                self.assertEqual(eligible, {name.removesuffix('.conf') for name in configuration})
                self.assertNotIn('socrat-3', eligible)

    def test_explicit_node_selector_remains_an_additional_constraint(self):
        resources = self.resources({'nodeSelector': {'homelab.io/storage': 'true'}})
        pod = next(item for item in resources if item['kind'] == 'DaemonSet')['spec']['template']['spec']
        self.assertEqual(pod['nodeSelector'], {'homelab.io/storage': 'true'})
        self.assertIn('nodeAffinity', pod['affinity'])

    def test_public_gui_does_not_require_private_node_configuration(self):
        resources = self.resources({'privateGui': {'enabled': False, 'nodes': []}})
        pod = next(item for item in resources if item['kind'] == 'DaemonSet')['spec']['template']['spec']
        self.assertNotIn('affinity', pod)

    def test_private_gui_rejects_empty_enrollment(self):
        result = self.render({'privateGui': {'nodes': []}})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('privateGui requires at least one configured node', result.stderr)


if __name__ == '__main__':
    unittest.main()
