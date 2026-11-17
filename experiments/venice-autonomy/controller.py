import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

ENGINES = ('mini_native', 'openhands', 'mini_text')
TASKS = ('median', 'clamp', 'escape_html')
PROVIDER_ERRORS = ('APIError', 'APITimeoutError', 'Timeout', 'AuthenticationError', 'PermissionDeniedError',
                   'BadRequestError', 'InternalServerError', 'RateLimitError', 'NotFoundError')


def save_state(path, state):
    state['updated_at'] = time.time()
    temporary = path.with_suffix('.new')
    with temporary.open('w') as stream:
        json.dump(state, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def initial_state(duration, rounds):
    if not 1 <= duration <= 7200 or not 1 <= rounds <= 10:
        raise ValueError('experiment must have 1..7200 seconds and 1..10 rounds')
    now = time.time()
    tasks = [{'id': f'{round_number}-{engine}-{task}', 'engine': engine, 'task': task,
              'seed': 170100 + round_number, 'status': 'pending', 'attempts': []}
             for round_number in range(rounds) for task in TASKS for engine in ENGINES]
    return {'schema': 1, 'created_at': now, 'deadline': now+duration, 'phase': 'running',
            'tasks': tasks, 'running': None, 'consecutive_provider_failures': 0,
            'controller_restarts': 0}


def settle_task(task, result, max_attempts=2):
    task['attempts'].append(result)
    task['status'] = ('accepted' if result.get('accepted') is True else
                      'blocked' if len(task['attempts']) >= max_attempts else 'pending')
    return task['status']


def recover_interrupted(state):
    running = state.get('running')
    if running:
        task = next(task for task in state['tasks'] if task['id'] == running['task_id'])
        settle_task(task, {'accepted': False, 'controller_error': 'interrupted_attempt',
                           'directory': running['directory']})
        state['running'] = None
    state['controller_restarts'] += 1


def cleanup_interrupted(running):
    pid = running['pid']
    expected_script = str(pathlib.Path(__file__).with_name('attempt.py'))
    try:
        command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'args='], text=True).strip()
        if expected_script in command and running['directory'] in command and os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGTERM)
            time.sleep(3)
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except (ProcessLookupError, subprocess.CalledProcessError):
        pass
    root = pathlib.Path(running['directory'])/'agent'
    container_file = root/'container-id'
    if container_file.exists():
        container_id = container_file.read_text().strip()
        inspection = subprocess.run(['docker', 'inspect', container_id], capture_output=True, text=True, timeout=15)
        if inspection.returncode == 0:
            info = json.loads(inspection.stdout)[0]
            if info['Config'].get('Labels', {}).get('venice-autonomy-lab') != 'true':
                raise ValueError('refusing to clean an unlabelled container')
            subprocess.run(['docker', 'rm', '-f', container_id], capture_output=True, check=True, timeout=25)
    volume_file = root/'volume-name'
    if volume_file.exists():
        volume = volume_file.read_text().strip()
        if not volume.startswith('venice-lab-'):
            raise ValueError('refusing to clean an unrelated volume')
        subprocess.run(['docker', 'volume', 'rm', volume], capture_output=True, timeout=20)


def write_report(root, state):
    rows = ['# Controlled autonomy experiment', '', f"Phase: `{state['phase']}`", '',
            '| Engine | Accepted tasks | Blocked tasks | Pending tasks | Recorded commands |',
            '|---|---:|---:|---:|---:|']
    for engine in ENGINES:
        tasks = [task for task in state['tasks'] if task['engine'] == engine]
        counts = [sum(task['status'] == status for task in tasks) for status in ('accepted', 'blocked', 'pending')]
        commands = sum(attempt.get('actual_commands', 0) for task in tasks for attempt in task['attempts'])
        rows.append(f'| {engine} | {counts[0]} | {counts[1]} | {counts[2]} | {commands} |')
    rows += ['', 'Acceptance comes from a fresh isolated verifier, never a model-written pass flag.',
             'These are small synthetic coding tasks, not a certification of general bug-finding or overnight reliability.',
             'Private event logs and candidates remain in this directory. There is no automatic commit, push or deploy.']
    (root/'REPORT.md').write_text('\n'.join(rows)+'\n')


def run(root, mini_python, openhands_python, duration, rounds):
    os.umask(0o077)
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise ValueError('controller root must be a private real directory')
    with (root/'controller.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = root/'state.json'
        if path.exists():
            state = json.loads(path.read_text())
            if state.get('running'):
                cleanup_interrupted(state['running'])
            recover_interrupted(state)
        else:
            state = initial_state(duration, rounds)
        source_hashes = {name: hashlib.sha256(pathlib.Path(__file__).with_name(name).read_bytes()).hexdigest()
                         for name in ('attempt.py', 'sandbox.py', 'fixtures.py', 'controller.py')}
        if state.get('source_hashes', source_hashes) != source_hashes:
            raise ValueError('runner source changed; refusing an incomparable resume')
        state['source_hashes'] = source_hashes
        save_state(path, state)
        try:
            while time.time() < state['deadline'] and state['phase'] == 'running':
                task = next((task for task in state['tasks'] if task['status'] == 'pending'), None)
                if task is None:
                    state['phase'] = 'queue_finished'
                    break
                directory = root/'runs'/(task['id']+'-attempt-'+str(len(task['attempts'])+1))
                directory.parent.mkdir(exist_ok=True)
                python = mini_python if task['engine'].startswith('mini_') else openhands_python
                command = [python, '-u', str(pathlib.Path(__file__).with_name('attempt.py')),
                           '--engine', task['engine'], '--task', task['task'], '--directory', str(directory),
                           '--seed', str(task['seed'])]
                if task['attempts']:
                    command += ['--feedback', json.dumps(task['attempts'][-1].get('verdict', {'accepted': False}))[:1800]]
                with (root/(task['id']+'-'+str(len(task['attempts'])+1)+'.log')).open('w') as log:
                    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    running = {'task_id': task['id'], 'pid': process.pid, 'directory': str(directory)}
                    state['running'] = running
                    save_state(path, state)
                    try:
                        process.wait(timeout=max(1, min(900, state['deadline']-time.time())))
                    except subprocess.TimeoutExpired:
                        cleanup_interrupted(running)
                        process.wait(timeout=10)
                summary_path = directory/'summary.json'
                try:
                    result = json.loads(summary_path.read_text())
                    if not isinstance(result, dict) or type(result.get('accepted')) is not bool:
                        raise ValueError('invalid summary')
                except (OSError, ValueError):
                    result = {'accepted': False, 'controller_error': 'missing_or_invalid_summary',
                              'process_exit': process.returncode}
                result['directory'] = str(directory)
                settle_task(task, result)
                if result.get('run_error_type') in PROVIDER_ERRORS:
                    state['consecutive_provider_failures'] += 1
                else:
                    state['consecutive_provider_failures'] = 0
                if state['consecutive_provider_failures'] >= 2:
                    state['phase'] = 'repeated_provider_failures'
                state['running'] = None
                save_state(path, state)
                write_report(root, state)
                print(json.dumps({'task': task['id'], 'status': task['status'], 'accepted': result.get('accepted')}), flush=True)
            if state['phase'] == 'running':
                state['phase'] = 'deadline_reached'
        except KeyboardInterrupt:
            if state.get('running'):
                cleanup_interrupted(state['running'])
                recover_interrupted(state)
            state['phase'] = 'operator_stopped'
        finally:
            save_state(path, state)
            write_report(root, state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--mini-python', required=True)
    parser.add_argument('--openhands-python', required=True)
    parser.add_argument('--duration-seconds', type=int, default=5400)
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    run(args.root, args.mini_python, args.openhands_python, args.duration_seconds, args.rounds)
