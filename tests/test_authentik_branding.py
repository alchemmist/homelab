"""Offline contract/security checks; no cluster access or temporary identities."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / 'deploy/authentik/quiet-mono'


def load(name):
    path = ROOT / 'ansible/roles/authentik/files' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthentikBrandingTests(unittest.TestCase):
    def test_approved_reference_is_frozen(self):
        root = THEME / 'reference'
        manifest = json.loads((root / 'manifest.json').read_text())
        self.assertGreaterEqual(len(manifest['files']), 15)
        for name, expected in manifest['files'].items():
            content = (root / name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), expected['sha256'], name)
            self.assertEqual(len(content), expected['bytes'], name)

    def test_cli_emits_individual_documents_for_strict_v3_validation(self):
        output = subprocess.check_output([
            sys.executable, str(ROOT / 'ansible/roles/authentik/files/branding_static.py'), str(THEME)
        ], text=True)
        documents = [json.loads(part) for part in output.split('---\n') if part.strip()]
        self.assertEqual(len(documents), 4)
        self.assertNotIn('List', [item['kind'] for item in documents])

    def test_static_asset_checksums(self):
        for item in json.loads((THEME / 'assets.json').read_text()).values():
            self.assertEqual(hashlib.sha256((THEME / item['path']).read_bytes()).hexdigest(), item['sha256'])

    def test_static_bundle_has_no_scripts_or_secrets(self):
        items = load('branding_static').render(THEME)['items']
        self.assertEqual([item['kind'] for item in items], ['ConfigMap', 'Deployment', 'Service', 'Ingress'])
        config = items[0]
        self.assertTrue(config['immutable'])
        self.assertNotIn('annotations', config['metadata'])
        self.assertTrue(all(Path(name).suffix in {'.webp', '.svg', '.woff2'} for name in config['binaryData']))
        self.assertNotIn('Secret', [item['kind'] for item in items])

    def test_static_pod_is_sandboxed_and_small(self):
        deployment = load('branding_static').render(THEME)['items'][1]
        pod = deployment['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertTrue(pod['securityContext']['runAsNonRoot'])
        container = pod['containers'][0]
        self.assertIn('@sha256:', container['image'])
        self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
        self.assertFalse(container['securityContext']['allowPrivilegeEscalation'])
        self.assertEqual(container['securityContext']['capabilities']['drop'], ['ALL'])
        self.assertEqual(container['resources']['limits']['memory'], '64Mi')

    def test_ingress_is_only_public_static_prefix(self):
        ingress = load('branding_static').render(THEME)['items'][3]
        self.assertEqual(ingress['spec']['rules'][0]['host'], 'auth.socrat.alchemmist.xyz')
        paths = ingress['spec']['rules'][0]['http']['paths']
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0]['path'], '/-/quiet-mono/v1/')
        self.assertEqual(ingress['spec']['tls'][0]['secretName'], 'authentik-tls')

    def test_fonts_and_mobile_photos_are_referenced(self):
        css = (THEME / 'theme.css').read_text()
        self.assertIn('__ASSET_COURIER__', css)
        self.assertIn('__ASSET_SERIF__', css)
        self.assertIn('__ASSET_CODE__', css)
        self.assertIn('__ASSET_LAKE_MOBILE__', css)
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn('::part(drawer-content)', css)
        self.assertNotIn('https://', css)

    def test_primary_action_style_also_covers_native_redirect_anchor(self):
        css = (THEME / 'theme.css').read_text()
        self.assertNotIn('button.pf-m-primary', css)
        self.assertIn(':is(button,a.pf-c-button).pf-m-primary', css)
        self.assertIn(':is(button,a.pf-c-button).pf-m-primary:hover::after', css)
        self.assertIn('box-sizing:border-box;text-decoration:none!important', css)

    def test_inspector_toggle_and_history_are_presentation_only(self):
        css = (THEME / 'theme.css').read_text()
        self.assertIn('ak-flow-inspector-button{position:fixed!important', css)
        self.assertIn('width:39px!important;height:39px!important', css)
        self.assertIn('i.fa-search-plus', css)
        self.assertIn('max-block-size:22rem;overflow-y:auto', css)
        self.assertNotIn('nth-child', css)
        self.assertNotIn('column-reverse', css)

    def test_reconciler_does_not_ship_a_replacement_frontend(self):
        source = (ROOT / 'ansible/roles/authentik/files/branding.py').read_text()
        self.assertNotIn('core/users/', source)
        self.assertNotIn('set_password', source)
        self.assertNotIn('providers/', source)
        self.assertNotIn('stages/authenticator/', source)
        self.assertNotIn('verify=False', source)
        self.assertIn('api/v3/', source)
        self.assertIn('2026.8.5', source)
        self.assertNotIn("api('POST', 'admin/file/", source)
        self.assertIn('/-/quiet-mono/v1/', source)

    def test_backups_have_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'backup.json'
            load('branding').protected_json(target, {'test': True})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_reference_stays_nonmodal(self):
        source = (THEME / 'reference/quiet-mono.js').read_text()
        self.assertNotIn('showModal(', source)
        self.assertIn('dialog.show()', source)
        self.assertIn('!dialog.open || inspectorClosing', source)

    def test_playbook_uses_explicit_apply_and_server_side_configmaps(self):
        source = (ROOT / 'ansible/playbooks/authentik-branding.yml').read_text()
        self.assertIn('authentik_branding_action: prepare', source)
        self.assertIn('--server-side', source)
        self.assertIn('become: false', source)
        self.assertNotIn('helm', source)


if __name__ == '__main__':
    unittest.main()
