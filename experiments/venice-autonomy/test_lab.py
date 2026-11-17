import io
import json
import tarfile
import unittest

from fixtures import cases_for, check_verdict, expected
from sandbox import inspect_archive


def archive(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as stream:
        for name, content, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            if kind == tarfile.REGTYPE:
                member.size = len(content)
            else:
                member.linkname = '/Users/owner/.ssh/id_ed25519'
            stream.addfile(member, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
    return buffer.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_regular_files(self):
        result = inspect_archive(archive([('lib.cjs', b'code', tarfile.REGTYPE), ('test.cjs', b'test', tarfile.REGTYPE)]))
        self.assertEqual(result, {'lib.cjs': 'code', 'test.cjs': 'test'})

    def test_symlink_is_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(archive([('lib.cjs', b'', tarfile.SYMTYPE)]))

    def test_hardlink_is_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(archive([('lib.cjs', b'', tarfile.LNKTYPE)]))

    def test_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(archive([('../lib.cjs', b'x', tarfile.REGTYPE)]))

    def test_absolute_is_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(archive([('/lib.cjs', b'x', tarfile.REGTYPE)]))

    def test_oversized_is_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(archive([('lib.cjs', b'x'*65537, tarfile.REGTYPE)]))

    def test_duplicate_is_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(archive([('lib.cjs', b'x', tarfile.REGTYPE)]*2))

    def test_missing_test_is_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(archive([('lib.cjs', b'x', tarfile.REGTYPE)]))

    def test_extra_file_is_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(archive([('lib.cjs', b'x', tarfile.REGTYPE), ('test.cjs', b'x', tarfile.REGTYPE), ('other', b'x', tarfile.REGTYPE)]))


class VerifierTests(unittest.TestCase):
    def test_expected(self):
        self.assertEqual(expected('median', [[10, 2, 1]]), {'value': 2})
        self.assertEqual(expected('median', [[1, 2]]), {'value': 1.5})
        self.assertEqual(expected('median', [[]]), {'error': 'RangeError'})
        self.assertEqual(expected('clamp', [8, -2, 0]), {'value': 0})
        self.assertEqual(expected('clamp', [1, 2, 0]), {'error': 'RangeError'})
        self.assertEqual(expected('escape_html', ['<&\'"']), {'value': '&lt;&amp;&#39;&quot;'})

    def test_zero_exit_without_output_is_not_success(self):
        self.assertFalse(check_verdict('median', 'nonce', [[[]]], {'returncode': 0, 'output': ''})['accepted'])

    def test_wrong_nonce_is_not_success(self):
        result = {'returncode': 0, 'output': json.dumps({'nonce': 'other', 'results': []})}
        self.assertFalse(check_verdict('median', 'nonce', [], result)['accepted'])

    def test_process_failure_is_not_success(self):
        result = {'returncode': 1, 'output': json.dumps({'nonce': 'nonce', 'results': []})}
        self.assertFalse(check_verdict('median', 'nonce', [], result)['accepted'])

    def test_each_contract_and_mutation(self):
        for task in ('median', 'clamp', 'escape_html'):
            cases = cases_for(task, 1234)
            results = [expected(task, args) | {'mutated': False} for args in cases]
            result = {'returncode': 0, 'output': json.dumps({'nonce': 'nonce', 'results': results})}
            self.assertTrue(check_verdict(task, 'nonce', cases, result)['accepted'])
            results[0]['mutated'] = True
            result['output'] = json.dumps({'nonce': 'nonce', 'results': results})
            self.assertFalse(check_verdict(task, 'nonce', cases, result)['accepted'])

    def test_deterministic_cases(self):
        self.assertEqual(cases_for('median', 123), cases_for('median', 123))
        self.assertNotEqual(cases_for('median', 123), cases_for('median', 124))

class ControllerTests(unittest.TestCase):
    def test_rejection_retries_then_blocks(self):
        from controller import settle_task
        task = {'attempts': [], 'status': 'pending'}
        self.assertEqual(settle_task(task, {'accepted': False}), 'pending')
        self.assertEqual(settle_task(task, {'accepted': False}), 'blocked')

    def test_only_typed_acceptance_counts(self):
        from controller import settle_task
        for result in ({'accepted': 'true'}, {'model_report': 'all tests passed'}, {'exit_status': 'stop'}):
            task = {'attempts': [], 'status': 'pending'}
            self.assertNotEqual(settle_task(task, result), 'accepted')
        task = {'attempts': [], 'status': 'pending'}
        self.assertEqual(settle_task(task, {'accepted': True}), 'accepted')

    def test_restart_preserves_deadline_and_rejects_unfinished_attempt(self):
        from controller import initial_state, recover_interrupted
        state = initial_state(120, 1)
        deadline = state['deadline']
        task = state['tasks'][0]
        state['running'] = {'task_id': task['id'], 'directory': '/private/test'}
        recover_interrupted(state)
        self.assertEqual(state['deadline'], deadline)
        self.assertEqual(task['status'], 'pending')
        self.assertFalse(task['attempts'][0]['accepted'])
        self.assertEqual(task['attempts'][0]['controller_error'], 'interrupted_attempt')
        self.assertIsNone(state['running'])

    def test_atomic_checkpoint(self):
        import pathlib
        import tempfile
        from controller import save_state
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)/'state.json'
            save_state(path, {'phase': 'running'})
            self.assertEqual(json.loads(path.read_text())['phase'], 'running')
            self.assertFalse(path.with_suffix('.new').exists())


class MiniAdapterTests(unittest.TestCase):
    def test_completed_receipt_formats_for_both_action_protocols(self):
        from unittest.mock import patch
        from minisweagent.models.litellm_model import LitellmModel
        from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel
        from sandbox import Sandbox
        import pathlib
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Sandbox.__new__(Sandbox)
            sandbox.directory = pathlib.Path(directory)
            sandbox.events = []
            sandbox.container_id = 'isolated-test-double'
            sandbox.verifier = False
            with patch('sandbox.bounded_process', return_value=(0, b'observed\n')):
                output = sandbox.execute({'command': 'echo observed'})
            self.assertIsNone(output['exception_info'])
            for model_type in (LitellmModel, LitellmTextbasedModel):
                model = model_type(model_name='openai/venice-deepseek', cost_tracking='ignore_errors')
                message = {'extra': {'actions': [{'command': 'echo observed', 'tool_call_id': 'call_fixture'}]}}
                messages = model.format_observation_messages(message, [output])
                self.assertIn('observed', messages[0]['content'])


if __name__ == '__main__':
    unittest.main()
