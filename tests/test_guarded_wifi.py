import contextlib
import gzip
import importlib.util
import io
import lzma
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'ansible/roles/debian_laptop/files/load_guarded_wifi.py'
SPEC = importlib.util.spec_from_file_location('guarded_wifi', SOURCE)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class GuardedWifiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.modules = self.root / 'modules'
        self.module = self.modules / 'test-kernel/updates/dkms/alx.ko'
        self.module.parent.mkdir(parents=True)
        self.module.write_bytes(b'module')
        self.board = self.root / 'board'
        self.board.write_text('MS-16GP\n')
        self.note = self.root / 'note'
        self.note.write_bytes(b'guarded-build-id')
        self.status = b'homelab-alx/6.12.111-1, test-kernel, x86_64: installed\n'
        self.wifi_parameters = self.root / 'wifi-parameters'
        self.wifi_parameters.mkdir()
        for name, value in {'msi': 'Y', 'ips': 'N', 'fwlps': 'N', 'swlps': 'N'}.items():
            (self.wifi_parameters / name).write_text(value + '\n')
        self.calls = []
        for patcher in (
            mock.patch.object(GUARD, 'BOARD_PATH', self.board),
            mock.patch.object(GUARD, 'LOADED_NOTE', self.note),
            mock.patch.object(GUARD, 'WIFI_PARAMETERS', self.wifi_parameters),
            mock.patch.object(GUARD.os, 'geteuid', return_value=0),
            mock.patch.object(GUARD.platform, 'release', return_value='test-kernel'),
            mock.patch.object(GUARD.platform, 'machine', return_value='x86_64'),
            mock.patch.object(GUARD, 'Path', side_effect=lambda value: self.modules if str(value) == '/lib/modules' else Path(value)),
            mock.patch.object(GUARD, 'module_note', return_value=b'guarded-build-id'),
            mock.patch.object(GUARD, 'run', side_effect=self.run_command),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_command(self, command):
        self.calls.append(command)
        if command[0] == 'dkms':
            return self.status
        if command[0] == 'modinfo':
            return str(self.module).encode()
        return b''

    def invoke(self, *arguments):
        with mock.patch('sys.argv', ['guard', *arguments]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return GUARD.main()

    def assert_wifi_not_loaded(self):
        self.assertFalse(any(call[:2] == ['modprobe', 'rtl8723ae'] for call in self.calls))

    def test_matching_loaded_identity_allows_wifi(self):
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.calls[-1], ['modprobe', 'rtl8723ae', 'msi=1', 'ips=0', 'fwlps=0', 'swlps=0'])

    def test_existing_wifi_with_wrong_parameters_fails_without_reload(self):
        for name in ('msi', 'ips', 'fwlps', 'swlps'):
            with self.subTest(parameter=name):
                path = self.wifi_parameters / name
                original = path.read_text()
                path.write_text('N' if name == 'msi' else 'Y')
                self.assertEqual(self.invoke(), 1)
                self.assertFalse(any('-r' in command or 'rmmod' in command for command in self.calls))
                path.write_text(original)

    def test_missing_wifi_parameter_fails(self):
        (self.wifi_parameters / 'msi').unlink()
        self.assertEqual(self.invoke(), 1)

    def test_installed_dkms_with_original_modules_annotation_is_accepted(self):
        self.status = b'homelab-alx/6.12.111-1, test-kernel, x86_64: installed (Original modules exist)\n'
        self.assertEqual(self.invoke(), 0)

    def test_unknown_dkms_annotation_is_rejected(self):
        self.status = b'homelab-alx/6.12.111-1, test-kernel, x86_64: installed (WARNING: mismatch)\n'
        self.assertEqual(self.invoke(), 1)
        self.assert_wifi_not_loaded()

    def test_check_never_loads_wifi(self):
        self.assertEqual(self.invoke('--check'), 0)
        self.assert_wifi_not_loaded()

    def test_old_running_module_rejected_even_when_dkms_installed(self):
        self.note.write_bytes(b'old-in-tree-build-id')
        self.assertEqual(self.invoke(), 1)
        self.assert_wifi_not_loaded()

    def test_wrong_kernel_or_uninstalled_dkms_rejected(self):
        for status in (b'', b'homelab-alx/6.12.111-1, other-kernel, x86_64: installed\n', b'homelab-alx/6.12.111-1, test-kernel, x86_64: built\n'):
            with self.subTest(status=status):
                self.status = status
                self.assertEqual(self.invoke(), 1)
                self.assert_wifi_not_loaded()
                self.assertNotIn(['modprobe', 'alx'], self.calls)

    def test_in_tree_module_rejected(self):
        self.module = self.modules / 'test-kernel/kernel/drivers/alx.ko'
        self.module.parent.mkdir(parents=True)
        self.module.write_bytes(b'in-tree')
        self.assertEqual(self.invoke(), 1)
        self.assert_wifi_not_loaded()

    def test_missing_loaded_note_rejected(self):
        self.note.unlink()
        self.assertEqual(self.invoke(), 1)
        self.assert_wifi_not_loaded()

    def test_wrong_board_rejected_without_commands(self):
        self.board.write_text('other-board')
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.calls, [])

    def test_nonroot_rejected_without_commands(self):
        with mock.patch.object(GUARD.os, 'geteuid', return_value=1000):
            self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.calls, [])


class ModuleNoteTests(unittest.TestCase):
    def test_decompression_and_note_extraction_preserve_original(self):
        for suffix, encode in (('.ko', lambda value: value), ('.ko.gz', gzip.compress), ('.ko.xz', lzma.compress)):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / ('alx' + suffix)
                encoded = encode(b'elf-module')
                source.write_bytes(encoded)

                def objcopy(command):
                    self.assertEqual(command[:2], ['objcopy', '--dump-section'])
                    self.assertEqual(Path(command[3]).read_bytes(), b'elf-module')
                    self.assertNotEqual(command[3], command[4])
                    Path(command[2].split('=', 1)[1]).write_bytes(b'note-section')
                    return b''

                with mock.patch.object(GUARD, 'run', side_effect=objcopy):
                    self.assertEqual(GUARD.module_note(source), b'note-section')
                self.assertEqual(source.read_bytes(), encoded)


if __name__ == '__main__':
    unittest.main()
