"""Regression checks for Argo's offline Helm render of Harbor."""
import subprocess
import json
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

class HarborGitopsRuntimeTests(unittest.TestCase):
    def render(self):
        return subprocess.check_output([
            'helm', 'template', 'harbor', 'charts/harbor', '-n', 'harbor',
            '-f', 'deploy/platform/harbor/values.yaml',
        ], cwd=ROOT, text=True)

    def test_two_offline_renders_are_identical(self):
        self.assertEqual(self.render(), self.render())

    def test_runtime_credentials_not_generated(self):
        resources = list(yaml.safe_load_all(self.render()))
        secrets = {r['metadata']['name'] for r in resources if r and r['kind'] == 'Secret'}
        # Trivy's connection config is deterministic, not a generated runtime key.
        self.assertEqual(secrets, {'harbor-trivy'})

    def test_home_ingress_disables_request_body_deadline_preserving_arguments(self):
        role = (ROOT / 'ansible/roles/home_ingress_ha/tasks/traefik.yml').read_text()
        for entrypoint in ('websecure', 'web'):
            self.assertIn(f'--entryPoints.{entrypoint}.transport.respondingTimeouts.readTimeout=0s', role)
        self.assertIn('.additionalArguments | default([])', role)
        self.assertIn('union([', role)

    def test_maintenance_policy_never_deletes_artifacts_or_tags(self):
        policy = json.loads((ROOT / 'deploy/platform/harbor/maintenance-policy.json').read_text())
        self.assertEqual(policy['gc']['schedule'], {'type': 'Weekly', 'cron': '0 0 3 * * 0'})
        self.assertIs(policy['gc']['parameters']['delete_untagged'], False)
        self.assertIs(policy['gc']['parameters']['delete_tag'], False)
        self.assertEqual(policy['gc']['parameters']['workers'], 1)
        self.assertEqual(policy['projects']['homelab']['auto_scan'], 'true')

    def test_oidc_config_uses_existing_secret(self):
        values = yaml.safe_load((ROOT / 'deploy/platform/harbor/values.yaml').read_text())
        env = next(e for e in values['core']['extraEnvVars'] if e['name'] == 'CONFIG_OVERWRITE_JSON')
        self.assertNotIn('value', env)
        self.assertEqual(env['valueFrom']['secretKeyRef'], {
            'name': 'socrat-authentik-harbor', 'key': 'config-json',
        })
        self.assertTrue(values['externallyManagedRuntimeSecrets'])
        self.assertTrue(values['trivy']['enabled'])
        self.assertEqual(values['trivy']['resources']['limits']['memory'], '1Gi')

if __name__ == '__main__':
    unittest.main()
