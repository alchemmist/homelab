"""Offline chart contract; no cluster API or credentials."""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('helm'), 'helm unavailable')
class AlertGraphsChartTests(unittest.TestCase):
    def render(self, enabled=False, extra=()):
        args = ['helm', 'template', 'kube-prometheus-stack', 'charts/grafana',
                '--namespace', 'cattle-monitoring-system']
        if enabled:
            args += ['--set', 'alertGraphs.enabled=true', '--set', 'alertGraphs.existingSecret=graph-test-only',
                     '--set', 'gateway.digest=sha256:' + 'a'*64,
                     '--set', 'grafana.imageRenderer.enabled=true',
                     '--set', 'grafana.imageRenderer.image.sha=' + 'b'*64,
                     '--set', 'alertGraphs.panels.service-health:12[0]=service']
        return subprocess.run(args+list(extra), cwd=ROOT, capture_output=True, text=True)

    def test_disabled_has_no_resources(self):
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('name: socrat-alert-graphs', result.stdout)

    def test_enabled_isolated_role(self):
        result = self.render(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('/app/graph_gateway.py', result.stdout)
        self.assertIn('name: socrat-alert-graphs', result.stdout)
        self.assertIn('automountServiceAccountToken: false', result.stdout)
        self.assertIn('readOnlyRootFilesystem: true', result.stdout)
        self.assertIn('checksum/policy:', result.stdout)
        self.assertNotIn('@sha256:sha256:',result.stdout)
        self.assertIn('@sha256:'+'b'*64,result.stdout)
        self.assertNotIn('mountPath: /data', result.stdout)
        self.assertNotIn('SPI_S3_WRITER_FILE', result.stdout)

    def test_release_values_render_real_valid_images(self):
        result=self.render(False, ['-f','charts/grafana/alert-graphs.policy.values.yaml',
                                  '-f','charts/grafana/alert-graphs.runtime.values.yaml',
                                  '-f','deploy/grafana/values.yaml'])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('@sha256:sha256:',result.stdout)
        import yaml,re
        for doc in yaml.safe_load_all(result.stdout):
            if not isinstance(doc,dict) or doc.get('kind')!='Deployment':continue
            for container in doc['spec']['template']['spec']['containers']:
                if container['name'] in ('gateway','grafana-image-renderer'):
                    self.assertRegex(container['image'],r'@sha256:[a-f0-9]{64}$')
                if container['name']=='grafana-image-renderer':
                    self.assertEqual(str(container['resources']['limits']['cpu']),'4')
                    self.assertEqual(container['resources']['limits']['memory'],'2Gi')

    def test_requires_immutable_image(self):
        result = self.render(True, ['--set', 'gateway.digest=latest'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('immutable', result.stderr)

    def test_requires_renderer(self):
        result = self.render(True, ['--set', 'grafana.imageRenderer.enabled=false'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('remote imageRenderer', result.stderr)

    def test_bot_sources_are_exact_only(self):
        result = self.render(True, ['--set', 'alertGraphs.botSourceCIDRs[0]=10.0.0.0/8'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exact /32 or /128', result.stderr)
        result = self.render(True, ['--set', 'alertGraphs.botSourceCIDRs[0]=10.250.0.2/32'])
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
