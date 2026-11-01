"""Offline regression checks; no live credentials or cluster operations."""
import ast
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import textwrap
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def controller():
    path = ROOT / 'ansible/roles/identity_integrations/files/litellm_oidc.py'
    spec = importlib.util.spec_from_file_location('litellm_oidc', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiteLLMIdentityTests(unittest.TestCase):
    def test_identity_mapping_uses_uuid_not_email_or_name(self):
        module = controller()
        owner = 'ad03842b-12a5-41e1-b875-fb712657e326'
        expression = module.identity_expression(owner, 'owner@example.org')
        namespace = {'request': SimpleNamespace(user=SimpleNamespace(uuid=owner, email='different@example.org'))}
        exec('def mapping():\n' + textwrap.indent(expression, '    '), namespace)
        self.assertEqual(namespace['mapping']()['litellm_user_id'], 'socrat-admin')
        self.assertEqual(namespace['mapping']()['litellm_user_role'], 'proxy_admin')
        self.assertEqual(namespace['mapping']()['litellm_user_email'], 'owner@example.org')
        other = 'ed03842b-12a5-41e1-b875-fb712657e326'
        namespace['request'].user = SimpleNamespace(uuid=other, email='owner@example.org', username='alchemmist')
        result = namespace['mapping']()
        self.assertEqual(result['litellm_user_id'], 'authentik:' + other)
        self.assertEqual(result['litellm_user_role'], 'internal_user_viewer')
        self.assertNotEqual(result['litellm_user_email'], 'owner@example.org')

    def test_catalog_is_owner_only_and_explicit_native_oidc(self):
        service = json.loads((ROOT / 'deploy/identity/services.json').read_text())['litellm']
        self.assertEqual(service['groups'], ['homelab-owner'])
        self.assertEqual(service['redirect'], 'https://llm.alchemmist.xyz/sso/callback')
        self.assertEqual(service['extraScopeMappings'], ['homelab-litellm-reviewed-identity'])
        self.assertIn('native-oidc', service['migration'])
        account = json.loads((ROOT / 'deploy/identity/account-mappings.json').read_text())['alchemmist']
        self.assertEqual(account['litellmUserId'], 'socrat-admin')

    def test_native_pkce_and_capacity_gate_are_not_bypassed(self):
        source = (ROOT / 'ansible/roles/identity_integrations/files/litellm_oidc.py').read_text()
        self.assertIn("'GENERIC_CLIENT_USE_PKCE': 'true'", source)
        self.assertIn('len(users) > 5', source)
        self.assertNotIn('LITELLM_LICENSE', source)
        self.assertNotIn('set_password', source)
        self.assertNotIn('verify=False', source)
        self.assertIn("'password'", source)  # Checks non-owner local-password boundary, does not reset it.

    def test_helm_replay_uses_optional_secret_refs(self):
        import yaml
        values = yaml.safe_load((ROOT / 'deploy/litellm/values.yaml').read_text())
        env = [e for e in values['extraEnvVars'] if e['name'].startswith('GENERIC_')]
        self.assertEqual(len(env), 10)
        for value in env:
            ref = value['valueFrom']['secretKeyRef']
            self.assertTrue(ref['optional'])
            self.assertEqual(ref['name'], 'socrat-authentik-litellm')
        self.assertTrue(values['proxy_config']['general_settings']['disable_env_credential_login'])

    def test_circle_is_original_high_resolution_artwork(self):
        sources = json.loads((ROOT / 'assets/service-icons/sources.json').read_text())['files']
        for slug in ['wiki']:
            record = sources[slug + '.svg']
            self.assertEqual(hashlib.sha256((ROOT / record['source']).read_bytes()).hexdigest(), record['source_sha256'])
            svg = ET.fromstring((ROOT / 'assets/service-icons' / (slug + '.svg')).read_bytes())
            image = next(iter(svg))
            content = base64.b64decode(image.attrib['{http://www.w3.org/1999/xlink}href'].split(',', 1)[1])
            self.assertEqual(struct.unpack('>II', content[16:24]), (512, 512))
        self.assertIn('/svg/argo-cd.svg', sources['argocd.svg']['url'])

    def test_litellm_uses_official_product_logo_not_wiki_artwork(self):
        sources = json.loads((ROOT / 'assets/service-icons/sources.json').read_text())['files']
        record = sources['litellm.svg']
        self.assertIn('githubusercontent.com/BerriAI/litellm/', record['url'])
        self.assertIn('/' + record['revision'] + '/', record['url'])
        self.assertTrue(record['url'].endswith('/litellm_monogram.svg'))
        content = (ROOT / 'assets/service-icons/litellm.svg').read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), record['sha256'])
        self.assertNotEqual(record['sha256'], sources['wiki.svg']['sha256'])
        svg = ET.fromstring(content)
        self.assertEqual(svg.attrib['viewBox'], '0 0 372.14 371.53')
        self.assertTrue(any(n.tag.endswith('path') for n in svg))
        self.assertFalse(any(n.tag.split('}')[-1] in ['script','foreignObject','image'] for n in svg.iter()))
        service = json.loads((ROOT / 'deploy/identity/services.json').read_text())['litellm']
        self.assertEqual(service['icon'], 'service-icons/litellm-' + record['sha256'][:12] + '.svg')

    def test_icon_reconciler_patches_only_icon_metadata(self):
        tree = ast.parse((ROOT / 'ansible/roles/authentik/files/icons.py').read_text())
        patches = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Name) and n.func.id == 'api'
                   and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == 'PATCH']
        self.assertEqual(len(patches), 1)
        self.assertEqual([key.value for key in patches[0].args[2].keys], ['meta_icon'])


if __name__ == '__main__':
    unittest.main()
