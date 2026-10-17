import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


SPEC = importlib.util.spec_from_file_location('bootstrap', Path(__file__).resolve().parents[1] / 'scripts/bootstrap-wiki-runtime.py')
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.resources = {
            ('clusters.fleet.cattle.io', 'local', 'fleet-local'): {'spec': {'agentNamespace': 'fleet-agent-local'}},
            ('secret', 'wiki-editor-git', 'wiki'): {'data': {'id_ed25519': BOOTSTRAP.encoded('private fixture')}},
            ('configmap', 'wiki-editor-hosts', 'wiki'): {'data': {'known_hosts': 'github.com fixture'}},
        }
        self.kube = Mock()
        self.kube.get.side_effect = lambda *key: self.resources.get(key)

    def test_creates_only_isolated_resources_without_registry_credentials(self):
        messages = BOOTSTRAP.bootstrap(self.kube)
        all_created = [call.args[0] for call in self.kube.create.call_args_list]
        self.assertEqual([item['kind'] for item in all_created[:4]], ['Namespace', 'ServiceAccount', 'Role', 'RoleBinding'])
        self.assertEqual(all_created[3]['subjects'][0]['namespace'], 'fleet-agent-local')
        created = all_created[4:]
        self.assertEqual([item['metadata']['name'] for item in created], ['wiki-runtime-data', 'wiki-runtime-bootstrap', 'wiki-runtime-git'])
        self.assertEqual(created[0]['metadata']['annotations']['helm.sh/resource-policy'], 'keep')
        self.assertEqual(BOOTSTRAP.decoded(created[2]['data']['known_hosts']), 'github.com fixture')
        self.assertFalse(any('ghcr-pull' in call.args or 'wiki-runtime-registry' in call.args for call in self.kube.get.call_args_list))
        self.assertNotIn('token:with:colons', str(messages))

    def test_repeated_run_never_rotates_bootstrap_or_existing_resources(self):
        BOOTSTRAP.bootstrap(self.kube)
        for call in self.kube.create.call_args_list:
            item = call.args[0]
            kind = item['kind'].lower()
            self.resources[kind, item['metadata']['name'], item['metadata'].get('namespace', 'wiki')] = item
        original = self.resources['secret', 'wiki-runtime-bootstrap', 'wiki']['data']['token']
        self.kube.create.reset_mock()
        BOOTSTRAP.bootstrap(self.kube)
        self.kube.create.assert_not_called()
        self.assertEqual(self.resources['secret', 'wiki-runtime-bootstrap', 'wiki']['data']['token'], original)

    def test_clean_install_can_skip_legacy_git(self):
        del self.resources['secret', 'wiki-editor-git', 'wiki']
        del self.resources['configmap', 'wiki-editor-hosts', 'wiki']
        messages = BOOTSTRAP.bootstrap(self.kube, skip_legacy_git=True)
        self.assertIn('wiki/wiki-runtime-git: skipped', messages)
        names = [call.args[0]['metadata']['name'] for call in self.kube.create.call_args_list]
        self.assertNotIn('wiki-runtime-git', names)

    def test_missing_sources_fail_before_any_creation(self):
        del self.resources['configmap', 'wiki-editor-hosts', 'wiki']
        with self.assertRaises(BOOTSTRAP.BootstrapError):
            BOOTSTRAP.bootstrap(self.kube)
        self.kube.create.assert_not_called()

    def test_invalid_existing_bootstrap_is_not_overwritten(self):
        self.resources['secret', 'wiki-runtime-bootstrap', 'wiki'] = {'data': {'token': BOOTSTRAP.encoded('short')}}
        with self.assertRaises(BOOTSTRAP.BootstrapError):
            BOOTSTRAP.bootstrap(self.kube)
        self.kube.create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
