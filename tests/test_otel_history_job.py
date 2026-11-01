import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('history_job', ROOT / 'scripts/otel-history-job.py')
JOB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(JOB)
SPEC = importlib.util.spec_from_file_location('history_coordinator', ROOT / 'scripts/otel-history-migrate.py')
COORDINATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COORDINATOR)


class HistoryJobTests(unittest.TestCase):
    def test_workspace_has_one_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with COORDINATOR.workspace_lock(path):
                with self.assertRaises(ValueError):
                    with COORDINATOR.workspace_lock(path):
                        self.fail('Concurrent writer acquired lock')
            with COORDINATOR.workspace_lock(path):
                self.assertEqual((path / '.migration.lock').stat().st_mode & 0o777, 0o600)

    def test_lock_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'other').write_text('original')
            (path / '.migration.lock').symlink_to(path / 'other')
            with self.assertRaises(OSError):
                with COORDINATOR.workspace_lock(path):
                    self.fail('Symlinked lock was accepted')
            self.assertEqual((path / 'other').read_text(), 'original')

    def prepare(self, root):
        binary = root / 'binary'
        binary.write_bytes(b'pinned-binary')
        backup = root / 'backup'
        backup.mkdir()
        receipt = root / 'receipt.json'
        receipt.write_text('{}')
        workspace = root / 'workspace'
        workspace.mkdir(mode=0o700)
        (workspace / 'state.json').write_text('{}')
        return binary, backup, workspace, receipt

    def test_launch_pins_binary_and_detaches(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, backup, workspace, receipt = self.prepare(Path(directory))
            with mock.patch.object(JOB.subprocess, 'Popen', return_value=SimpleNamespace(pid=123)) as spawn:
                result = JOB.launch(binary, backup, workspace, receipt, 1024, 60)
            run = Path(result['runDirectory'])
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertEqual((run / 'otel-history').read_bytes(), b'pinned-binary')
            self.assertEqual((run / 'otel-history').stat().st_mode & 0o777, 0o700)
            self.assertEqual((run / 'worker.log').stat().st_mode & 0o777, 0o600)
            request = json.loads((run / 'request.json').read_text())
            self.assertEqual(request['environment']['GOMAXPROCS'], '2')
            self.assertTrue(request['memoryLimitIsSoft'])
            self.assertFalse(request['productionModified'])

    def test_failure_is_recorded_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, backup, workspace, receipt = self.prepare(Path(directory))
            with mock.patch.object(JOB.subprocess, 'Popen', return_value=SimpleNamespace(pid=123)):
                run = Path(JOB.launch(binary, backup, workspace, receipt, 1024, 60)['runDirectory'])
            with mock.patch.object(JOB.subprocess, 'run', return_value=SimpleNamespace(returncode=7)):
                self.assertEqual(JOB.execute(run), 1)
            result = json.loads((run / 'result.json').read_text())
            self.assertEqual(result['returnCode'], 7)
            self.assertFalse(result['success'])

    def test_corrupted_pinned_binary_is_never_launched(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, backup, workspace, receipt = self.prepare(Path(directory))
            with mock.patch.object(JOB.subprocess, 'Popen', return_value=SimpleNamespace(pid=123)):
                run = Path(JOB.launch(binary, backup, workspace, receipt, 1024, 60)['runDirectory'])
            (run / 'otel-history').write_bytes(b'corrupted')
            with mock.patch.object(JOB.subprocess, 'run') as execute:
                self.assertEqual(JOB.execute(run), 1)
                execute.assert_not_called()

    def test_world_readable_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, backup, workspace, receipt = self.prepare(Path(directory))
            workspace.chmod(0o755)
            with self.assertRaises(ValueError):
                JOB.launch(binary, backup, workspace, receipt, 1024, 60)


if __name__ == '__main__':
    unittest.main()
