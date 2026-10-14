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


if __name__ == '__main__':
    unittest.main()
