import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class ControllerFaultTests(unittest.TestCase):
    def setup_case(self, directory, behavior):
        root = pathlib.Path(directory)
        code = root/'code'
        code.mkdir()
        shutil.copy(pathlib.Path(__file__).with_name('controller.py'), code/'controller.py')
        for name in ('fixtures.py', 'sandbox.py'):
            (code/name).write_text('')
        fake = '''import argparse,json,pathlib,sys,time
p=argparse.ArgumentParser();p.add_argument('--directory');a,rest=p.parse_known_args()
d=pathlib.Path(a.directory);d.mkdir(parents=True)
'''
        if behavior == 'restart':
            fake += "marker=pathlib.Path(__file__).with_name('once');\nif not marker.exists():\n marker.write_text('started');time.sleep(600)\n"
            fake += "(d/'summary.json').write_text(json.dumps({'accepted':False,'run_error_type':'APITimeoutError'}))\n"
        elif behavior == 'premature_final':
            fake += "(d/'summary.json').write_text(json.dumps({'accepted':False,'exit_status':'stop','actual_commands':0}))\n"
        elif behavior == 'malformed_summary':
            fake += "(d/'summary.json').write_text('{broken');sys.exit(7)\n"
        (code/'attempt.py').write_text(fake)
        result = root/'private-state'
        return result, [sys.executable, str(code/'controller.py'), '--root', str(result),
                        '--mini-python', sys.executable, '--openhands-python', sys.executable,
                        '--duration-seconds', '30', '--rounds', '1']

    def test_model_final_is_not_verified_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, 'premature_final')
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=15)
            state = json.loads((root/'state.json').read_text())
            self.assertEqual(state['phase'], 'queue_finished')
            self.assertTrue(all(task['status'] == 'blocked' for task in state['tasks']))
            self.assertTrue(all(len(task['attempts']) == 2 for task in state['tasks']))

    def test_malformed_summaries_are_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, 'malformed_summary')
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=15)
            state = json.loads((root/'state.json').read_text())
            self.assertEqual(state['phase'], 'runner_infrastructure_error')
            attempts = [attempt for task in state['tasks'] for attempt in task['attempts']]
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0]['controller_error'], 'missing_or_invalid_summary')
            self.assertFalse(any(task['status'] == 'accepted' for task in state['tasks']))

    def test_kill_resume_preserves_deadline_and_stops_after_repeated_provider_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, 'restart')
            original = subprocess.Popen(command, stdout=subprocess.DEVNULL)
            restarted = None
            try:
                for _ in range(100):
                    if (root/'state.json').exists():
                        state = json.loads((root/'state.json').read_text())
                        if state.get('running'):
                            break
                    time.sleep(0.05)
                else:
                    self.fail('controller did not checkpoint its running child')
                child = state['running']['pid']
                deadline = state['deadline']
                original.kill()
                original.wait(timeout=5)
                time.sleep(0.2)
                restart_command = command.copy()
                restart_command[restart_command.index('--duration-seconds')+1] = '7000'
                restarted = subprocess.Popen(restart_command, stdout=subprocess.DEVNULL)
                restarted.wait(timeout=15)
                state = json.loads((root/'state.json').read_text())
                self.assertEqual(state['deadline'], deadline)
                self.assertEqual(state['phase'], 'repeated_provider_failures')
                self.assertEqual(state['controller_restarts'], 1)
                self.assertEqual(state['tasks'][0]['attempts'][0]['controller_error'], 'interrupted_attempt')
                self.assertFalse(any(task['status'] == 'accepted' for task in state['tasks']))
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    pass
                else:
                    self.fail('interrupted child is still alive')
            finally:
                for process in (original, restarted):
                    if process and process.poll() is None:
                        process.kill()
                        process.wait()


if __name__ == '__main__':
    unittest.main()
