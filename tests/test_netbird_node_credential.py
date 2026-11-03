import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('credential', ROOT/'scripts/netbird-node-credential.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CredentialTest(unittest.TestCase):
    def setup_runtime(self, folder, days):
        old = {'user_id': 'service-id', 'token_id': 'old-id', 'token': 'fixture-old',
               'expiration_date': (dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=days)).isoformat()}
        c.mod.atomic(folder/'credential.json', old)
        calls = []
        users = [{'id': 'service-id', 'name': c.mod.SERVICE, 'role': 'admin',
                  'is_service_user': True, 'is_blocked': False}]

        class Runtime:
            def __init__(self, root, config):self.auth = dict(old)
            def api(self, method, path, body=None):
                calls.append((method, path))
                if method == 'GET':return users
                if method == 'POST':return {'plain_token': 'fixture-new', 'personal_access_token': {
                    'id': 'new-id', 'expiration_date': (dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=365)).isoformat()}}
                if method == 'DELETE':
                    # On-disk new credential is verified and committed before old revocation.
                    assert json.loads((folder/'credential.json').read_text())['token_id'] == 'new-id'
        return Runtime, calls, users

    def test_valid_long_lived_token_does_not_rotate_each_run(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t); runtime, calls, users = self.setup_runtime(folder, 300)
            with patch.object(c.mod, 'Runtime', runtime):self.assertFalse(c.renew(folder, {}))
            self.assertEqual(calls, [('GET', 'users')])

    def test_renew_verify_atomic_switch_then_revoke_old(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t); runtime, calls, users = self.setup_runtime(folder, 10)
            with patch.object(c.mod, 'Runtime', runtime):self.assertTrue(c.renew(folder, {}))
            self.assertEqual([method for method, path in calls], ['GET', 'POST', 'GET', 'DELETE'])
            self.assertFalse((folder/'credential-intent.json').exists())
            self.assertEqual((folder/'credential.json').stat().st_mode & 0o777, 0o600)

    def test_human_blocked_or_lowered_account_not_repaired(self):
        for field,value in [('is_service_user',False),('is_blocked',True),('role','user')]:
            with tempfile.TemporaryDirectory() as t:
                folder = Path(t);runtime,calls,users = self.setup_runtime(folder, 10);users[0][field] = value
                with patch.object(c.mod,'Runtime',runtime),self.assertRaises(ValueError):c.renew(folder,{})
                self.assertEqual(calls,[('GET','users')])

    def test_uncertain_issuance_never_retries(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);(folder/'credential-intent.json').write_text('{}')
            with self.assertRaises(ValueError):c.renew(folder,{})

    def test_missing_credential_needs_explicit_bootstrap(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):c.renew(Path(t),{})
