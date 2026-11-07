"""Offline structural safety gates; not a live Django integration proof."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IdentityGuards(unittest.TestCase):
    def test_helper_is_explicit_atomic_and_scoped(self):
        source = (ROOT/'scripts/rustfs/unified_identity.py').read_text()
        ast.parse(source)
        for guard in ('with transaction.atomic():', 'select_for_update()',
                      "if action == 'plan':", "if action == 'rollback':",
                      "os.O_EXCL", '0o600', '0o700', "native_guard",
                      "'created_hash'", 'rollback CAS drift',
                      "mode='forward_single'", "internal_host=''",
                      'provider.set_oauth_defaults()', 'outpost.providers.add(provider)',
                      'outpost.providers.remove(provider)', 'no adoption/overwrite'):
            self.assertIn(guard, source)
        tree = ast.parse(source)
        # No writes to native user/groups/scope; only newly created proxy/app.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id in ('human', 'native', 'scope', 'app_native'):
                    self.assertNotIn(node.func.attr, ('save', 'delete', 'update'))
        self.assertNotIn("if __name__", source)  # import does not run provisioner
        self.assertIn("hashlib.sha256(provider.client_secret.encode()).hexdigest()", source)
        self.assertNotIn('cookie_secret', source)
        self.assertIn('PolicyBinding.objects.create(target_id=app.pk', source)
        self.assertNotIn('PolicyBinding.objects.create(target=app.pk', source)

    def test_normalized_authority_guard(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('unified_identity', ROOT/'scripts/rustfs/unified_identity.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        expected = module.authority(module.HOST)
        for url in ('https://rustfs.socrat.alchemmist.xyz', 'https://RUSTFS.socrat.alchemmist.xyz:443/', 'https://rustfs.socrat.alchemmist.xyz./'):
            self.assertEqual(module.authority(url), expected)
        self.assertNotEqual(module.authority('https://rustfs.socrat.alchemmist.xyz:444/'), expected)
        for url in ('//rustfs.socrat.alchemmist.xyz', 'https://user:secret@rustfs.socrat.alchemmist.xyz'):
            with self.assertRaises(ValueError): module.authority(url)
        self.assertIn("actual['client_id']", (ROOT/'scripts/rustfs/unified_identity.py').read_text())
