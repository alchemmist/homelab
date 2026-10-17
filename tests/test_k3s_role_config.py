import argparse
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest

import yaml

MODULE_PATH = Path(__file__).resolve().parents[1] / 'ansible/roles/k3s_role_rebalance/files/configure_role.py'
SPEC = importlib.util.spec_from_file_location('configure_role', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RoleConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'config.yaml'
        self.args = argparse.Namespace(
            config=str(self.path), role='server', node_name='socrat-3',
            node_ip='10.250.0.5', advertise_ip='10.250.0.5',
            server='https://10.250.0.1:6443', token_file='/etc/rancher/k3s/token', check=False,
        )

    def write(self, value):
        self.path.write_text(yaml.safe_dump(value))
        self.path.chmod(0o600)

    def read(self):
        return yaml.safe_load(self.path.read_text())

    def test_promote_preserves_worker_settings(self):
        preserved = {
            'prefer-bundled-bin': True, 'node-label': ['workload=llm'],
            'kubelet-arg': ['eviction-hard=memory.available<100Mi'],
            'node-taint': ['dedicated=llm:NoSchedule'], 'disable': ['servicelb'],
        }
        self.write(dict(preserved, **{'disable-etcd': True, 'cluster-init': True, 'tls-san': ['existing.example']}))
        result = MODULE.configure(self.args)
        self.assertTrue(result['changed'])
        actual = self.read()
        for key, value in preserved.items():
            self.assertEqual(actual[key], value)
        self.assertNotIn('disable-etcd', actual)
        self.assertNotIn('cluster-init', actual)
        self.assertEqual(actual['tls-san'], ['existing.example', '10.250.0.5', '127.0.0.1'])
        self.assertEqual(actual['token-file'], self.args.token_file)
        self.assertEqual(actual['flannel-iface'], 'wg-socrat')

    def test_explicit_token_file_replaces_inline_token_only(self):
        self.write({'token': 'old-agent-token', 'token-file': '/old/token', 'disable-agent': False, 'node-label': ['a=b']})
        MODULE.configure(self.args)
        actual = self.read()
        self.assertNotIn('token', actual)
        self.assertEqual(actual['token-file'], self.args.token_file)
        self.assertFalse(actual['disable-agent'])
        self.assertEqual(actual['node-label'], ['a=b'])

    def test_control_plane_removes_conflicting_flags(self):
        self.write({key: True for key in ('cluster-init', 'disable-apiserver', 'disable-controller-manager', 'disable-scheduler')})
        self.args.role = 'control-plane'
        MODULE.configure(self.args)
        actual = self.read()
        self.assertTrue(actual['disable-etcd'])
        for key in ('cluster-init', 'disable-apiserver', 'disable-controller-manager', 'disable-scheduler'):
            self.assertNotIn(key, actual)

    def test_idempotence_private_backup_and_atomic_permissions(self):
        self.write({'node-label': ['a=b']})
        self.path.chmod(0o644)
        original = self.path.read_bytes()
        first = MODULE.configure(self.args)
        backup = self.path.parent / first['backup']
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        inode = self.path.stat().st_ino
        self.assertEqual(MODULE.configure(self.args), {'changed': False, 'backup': None})
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertEqual(len(list(self.path.parent.glob('*.backup-*'))), 1)
        self.args.node_name = 'socrat-1'
        second = MODULE.configure(self.args)
        self.assertNotEqual(first['backup'], second['backup'])
        self.assertEqual(backup.read_bytes(), original)

    def test_check_does_not_write(self):
        self.write({'token-file': '/existing/token'})
        self.args.token_file = None
        self.args.check = True
        original = self.path.read_bytes()
        self.assertTrue(MODULE.configure(self.args)['changed'])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.args.check = False
        MODULE.configure(self.args)
        self.assertEqual(self.read()['token-file'], '/existing/token')

    def test_rejects_symlink_and_non_mapping(self):
        self.write(['invalid'])
        with self.assertRaises(ValueError):
            MODULE.configure(self.args)
        target = self.path.with_name('target.yaml')
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            MODULE.configure(self.args)


if __name__ == '__main__':
    unittest.main()
