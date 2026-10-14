import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'ansible/files/helm_manifest_changed.py'
ARGUMENTS = [str(SCRIPT), '--release', 'syncthing', '--chart', '/chart',
             '--namespace', 'syncthing', '--values', '/values', '--kubeconfig', '/config']


class HelmManifestComparisonTests(unittest.TestCase):
    def compare(self, installed, desired='manifest\n'):
        output = io.StringIO()
        rendered = subprocess.CompletedProcess(['helm', 'template'], 0, desired, '')
        with patch('sys.argv', ARGUMENTS), patch('subprocess.run', side_effect=[rendered, installed]):
            with contextlib.redirect_stdout(output):
                runpy.run_path(str(SCRIPT), run_name='__main__')
        return json.loads(output.getvalue())

    def test_equal_manifests_skip_upgrade(self):
        result = self.compare(subprocess.CompletedProcess(['helm', 'get'], 0, 'manifest\n', ''))
        self.assertFalse(result['changed'])

    def test_changed_manifest_requires_upgrade(self):
        result = self.compare(subprocess.CompletedProcess(['helm', 'get'], 0, 'old manifest', ''))
        self.assertTrue(result['changed'])

    def test_missing_release_allows_installation(self):
        result = self.compare(subprocess.CompletedProcess(['helm', 'get'], 1, '', 'Error: release: not found\n'))
        self.assertTrue(result['changed'])

    def test_read_failure_aborts_without_authorizing_upgrade(self):
        for error in ['Error: Kubernetes cluster unreachable', 'Error: forbidden', 'unexpected error']:
            with self.subTest(error=error), self.assertRaises(subprocess.CalledProcessError):
                self.compare(subprocess.CompletedProcess(['helm', 'get'], 1, '', error))


if __name__ == '__main__':
    unittest.main()
