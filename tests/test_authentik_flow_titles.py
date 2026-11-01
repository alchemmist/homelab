import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('flow_titles', ROOT / 'ansible/roles/authentik/files/flow_titles.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FlowTitleTests(unittest.TestCase):
    def test_title_only_idempotence_and_original_rollback(self):
        rows = {slug: {'pk': slug, 'title': 'Redirecting to %(app)s', 'designation': 'authorization'} for slug in module.TITLES}
        calls = []
        def api(method, path, value=None):
            slug = path.split('/')[2]
            if method == 'PATCH':
                self.assertEqual(set(value), {'title'})
                calls.append(slug)
                rows[slug].update(value)
            return copy.deepcopy(rows[slug])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(module.reconcile(api, root))
            backup = root / 'authorization-flow-titles-original.json'
            original = backup.read_bytes()
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(calls), 2)
            self.assertFalse(module.reconcile(api, root))
            self.assertEqual(backup.read_bytes(), original)
            self.assertTrue(all(row['title'] == 'Redirecting' for row in rows.values()))
            self.assertTrue(module.reconcile(api, root, rollback=True))
            self.assertTrue(all(row['title'] == 'Redirecting to %(app)s' for row in rows.values()))

    def test_rollback_refuses_different_flow_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = {slug: {'pk': slug, 'title': 'Redirecting to %(app)s'} for slug in module.TITLES}
            def api(method, path, value=None):
                slug = path.split('/')[2]
                if value: rows[slug].update(value)
                return copy.deepcopy(rows[slug])
            module.reconcile(api, root)
            rows[next(iter(rows))]['pk'] = 'different'
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                module.reconcile(api, root, rollback=True)


if __name__ == '__main__':
    unittest.main()
