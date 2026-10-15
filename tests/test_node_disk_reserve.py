import importlib.util
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


SOURCE = Path(__file__).resolve().parents[1] / 'ansible/roles/node_disk_reserve/files/configure_node_disk_reserve.py'
SPEC = importlib.util.spec_from_file_location('node_disk_reserve', SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PauseFolderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Path(self.directory.name) / 'config.xml'
        self.config.write_text('<configuration><gui><apikey>test-key</apikey></gui><folder id="pg-mdb-backups"><paused>false</paused></folder><folder id="notes"><paused>false</paused></folder></configuration>')
        self.config.chmod(0o600)

    def test_only_backup_folder_is_paused_and_credentials_are_preserved(self):
        with patch.object(MODULE.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            self.assertTrue(MODULE.pause_folder(self.config, 'pg-mdb-backups'))
        root = ET.fromstring(self.config.read_bytes())
        self.assertEqual(root.findtext("folder[@id='pg-mdb-backups']/paused"), 'true')
        self.assertEqual(root.findtext("folder[@id='notes']/paused"), 'false')
        self.assertEqual(root.findtext('gui/apikey'), 'test-key')
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_repeated_pause_does_not_rewrite_configuration(self):
        with patch.object(MODULE.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            MODULE.pause_folder(self.config, 'pg-mdb-backups')
        before = self.config.stat().st_mtime_ns
        self.assertFalse(MODULE.pause_folder(self.config, 'pg-mdb-backups'))
        self.assertEqual(self.config.stat().st_mtime_ns, before)

    def test_missing_folder_leaves_configuration_unchanged(self):
        original = self.config.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Missing Syncthing folder'):
            MODULE.pause_folder(self.config, 'missing')
        self.assertEqual(self.config.read_bytes(), original)


class ServiceSelectionTests(unittest.TestCase):
    def test_service_policy_controls_apply_and_rollback(self):
        for service in (None, 'k3s.service'):
            for fail_restart in (False, True):
                with self.subTest(service=service, fail_restart=fail_restart), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    syncthing = root / 'config.xml'
                    syncthing.write_text('<configuration/>')
                    kubelet = root / 'kubelet.conf'
                    kubelet.write_bytes(b'previous')
                    policy = {
                        'node': 'socrat-1', 'folder': 'pg-mdb-backups',
                        'kubelet': {'kind': 'KubeletConfiguration',
                                    'apiVersion': 'kubelet.config.k8s.io/v1beta1',
                                    'imageGCLowThresholdPercent': 95,
                                    'imageGCHighThresholdPercent': 96},
                    }
                    if service is not None:
                        policy['service'] = service
                    expected = service or 'k3s-agent.service'
                    effects = ([subprocess.CalledProcessError(1, 'systemctl'),
                                subprocess.CompletedProcess([], 0)] if fail_restart else None)
                    with patch.object(MODULE, 'SYNCTHING_CONFIG', syncthing), \
                         patch.object(MODULE, 'KUBELET_CONFIG', kubelet), \
                         patch.object(MODULE, 'Path', return_value=root / 'backups'), \
                         patch.object(MODULE.os, 'geteuid', return_value=0), \
                         patch.object(MODULE.os, 'statvfs'), \
                         patch.object(MODULE.socket, 'gethostname', return_value='socrat-1'), \
                         patch.object(MODULE, 'pause_folder', return_value=False), \
                         patch.object(MODULE.subprocess, 'run', side_effect=effects) as run:
                        if fail_restart:
                            with self.assertRaises(subprocess.CalledProcessError):
                                MODULE.apply(policy)
                            self.assertEqual(kubelet.read_bytes(), b'previous')
                            self.assertEqual(run.call_args_list[1].args[0], ['systemctl', 'restart', expected])
                        else:
                            MODULE.apply(policy)
                            self.assertEqual(run.call_args_list[1].args[0], ['systemctl', 'is-active', '--quiet', expected])
                        self.assertEqual(run.call_args_list[0].args[0], ['systemctl', 'restart', expected])


if __name__ == '__main__':
    unittest.main()
