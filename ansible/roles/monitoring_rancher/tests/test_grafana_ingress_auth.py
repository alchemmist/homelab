import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'grafana_ingress_auth', Path(__file__).parents[1] / 'files' / 'grafana_ingress_auth.py'
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def encoded(value):
    return base64.b64encode(value.encode()).decode()


class IngressAuthTests(unittest.TestCase):
    def reconcile(self, existing='', password='test-password'):
        admin = {'data': {'admin-user': encoded('admin'), 'admin-password': encoded(password)}}
        current = {'data': {'users': encoded(existing)}} if existing else None
        writes = []

        def kube(*args, input_data=None):
            if 'apply' in args:
                writes.append(json.loads(input_data))
                return b'applied'
            if 'source' in args:
                return json.dumps(admin).encode()
            return json.dumps(current).encode() if current else b''

        def openssl(argv, input=None, **kwargs):
            self.assertNotIn(password, argv)
            self.assertEqual(input, password.encode() + b'\n')
            salt = argv[argv.index('-salt') + 1]
            digest = 'different' if password == 'rotated' else 'digest'
            return ('$apr1$' + salt + '$' + digest + '\n').encode()

        output = io.StringIO()
        with patch.object(sys, 'argv', ['helper', '--namespace', 'test', '--admin-secret', 'source', '--auth-secret', 'dest']), patch.object(MODULE, 'kubectl', side_effect=kube), patch.object(MODULE.subprocess, 'check_output', side_effect=openssl), contextlib.redirect_stdout(output):
            MODULE.main()
        return output.getvalue().strip(), writes

    def test_creates_auth_secret_without_plaintext(self):
        state, writes = self.reconcile()
        self.assertEqual(state, 'changed')
        self.assertEqual(writes[0]['metadata']['name'], 'dest')
        users = base64.b64decode(writes[0]['data']['users']).decode()
        self.assertTrue(users.startswith('admin:$apr1$'))
        self.assertNotIn('test-password', json.dumps(writes))

    def test_existing_hash_is_not_regenerated(self):
        state, writes = self.reconcile('admin:$apr1$somesalt$digest\n')
        self.assertEqual(state, 'unchanged')
        self.assertEqual(writes, [])

    def test_password_rotation_updates_existing_hash(self):
        state, writes = self.reconcile('admin:$apr1$somesalt$digest\n', 'rotated')
        self.assertEqual(state, 'changed')
        self.assertEqual(base64.b64decode(writes[0]['data']['users']).decode(), 'admin:$apr1$somesalt$different\n')

    def test_rejects_newline_password(self):
        with self.assertRaises(ValueError):
            self.reconcile(password='password\nextra')


if __name__ == '__main__':
    unittest.main()
