import argparse
import collections
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import shlex
import signal
import subprocess
import sys
import tarfile
import time
import tokenize
import uuid

from sandbox import bounded_process


def require_path(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise RuntimeError(name + ' is required')
    path = pathlib.Path(value)
    if not path.is_dir():
        raise RuntimeError(name + ' is not a directory')
    return path


def load_local(name):
    path = pathlib.Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location('venice_autonomy_' + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_protocol():
    root = require_path('AUTONOMY_PROTOCOL_ROOT')
    local = str(pathlib.Path(__file__).resolve().parent)
    sys.path.insert(0, str(root))
    sys.path.insert(0, local)
    import protocol_regression
    return protocol_regression


def invoke_openhands(attempt_module, environment, directory, prompt, base_url, key, acceptance):
    return attempt_module.run_openhands(
        environment, directory, prompt, base_url, key,
        acceptance=acceptance, max_iterations=30, language='Python')


class RepositoryEnvironment:
    def __init__(self, snapshot, directory, image, protocol):
        self.directory = directory
        self.directory.mkdir()
        self.events = []
        self.protocol = protocol
        self.image = image
        self.nonce = os.environ.get('AUTONOMY_RUN_NONCE') or uuid.uuid4().hex
        self.container_id = None
        self.volume_name = 'venice-e2e-' + self.nonce[:16]
        subprocess.run([
            'docker', 'volume', 'create', '--driver', 'local', '--opt', 'type=tmpfs',
            '--opt', 'device=tmpfs', '--opt', 'o=size=32m,mode=0777',
            '--label', 'venice-e2e-run=' + self.nonce, self.volume_name,
        ], check=True, capture_output=True, timeout=30)
        self.config = {'image': image, 'network': 'none', 'read_only': True, 'repository': 'historical venice-api'}
        args = [
            'docker', 'run', '-d', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--memory', '512m', '--cpus', '1',
            '--pids-limit', '128', '--user', 'nobody', '--label', 'venice-e2e-run=' + self.nonce,
            '--label', 'venice-e2e-role=agent', '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m',
            '--volume', self.volume_name + ':/workspace:Z', '-w', '/workspace', '-e', 'HOME=/tmp',
            '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PYTHONNOUSERSITE=1', image, 'sleep', '20m',
        ]
        self.container_id = subprocess.check_output(args, text=True, timeout=45).strip()
        try:
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode='w') as archive:
                source = pathlib.Path(os.environ['AUTONOMY_SOURCE_CANDIDATE']) if os.getenv('AUTONOMY_SOURCE_CANDIDATE') else snapshot / 'agent'
                for name in protocol.WHITELIST:
                    data = (source / name).read_bytes()
                    item = tarfile.TarInfo(name)
                    item.mode = 0o666
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
            subprocess.run(['docker', 'cp', '-', self.container_id + ':/workspace'], input=payload.getvalue(), capture_output=True, check=True, timeout=30)
            info = json.loads(subprocess.check_output(['docker', 'inspect', self.container_id], timeout=15))[0]
            host = info['HostConfig']
            if host['NetworkMode'] != 'none' or host['ReadonlyRootfs'] is not True:
                raise RuntimeError('worker isolation check failed')
            if host['Memory'] != 512 * 1024 * 1024 or host['PidsLimit'] != 128 or info['Config']['User'] != 'nobody':
                raise RuntimeError('worker limit check failed')
            self.security = {
                'user': info['Config']['User'], 'network': host['NetworkMode'],
                'read_only': host['ReadonlyRootfs'], 'memory': host['Memory'], 'pids': host['PidsLimit'],
            }
            (directory / 'security.json').write_text(json.dumps(self.security, indent=2))
            result = self.execute({'command': 'python -c "import fastapi,jsonschema,playwright; from pathlib import Path; p=Path(\'/workspace/.preflight\');p.write_text(\'ok\');p.unlink();print(\'WORKER_READY\')"'})
            if result['returncode'] != 0 or 'WORKER_READY' not in result['output']:
                raise RuntimeError('worker preflight failed')
        except BaseException:
            self.close()
            raise

    def execute(self, action, **kwargs):
        command = action.get('command') if isinstance(action, dict) else None
        if not isinstance(command, str) or len(command.encode()) > 12000:
            raise ValueError('invalid or oversized command')
        started = time.monotonic()
        try:
            wrapped = 'timeout -k 3 40 bash -lc ' + shlex.quote(command) + ' 2>&1 | head -c 23000; status=${PIPESTATUS[0]}; exit "$status"'
            code, data = bounded_process(['docker', 'exec', self.container_id, 'bash', '-lc', wrapped], 24000, 50)
            result = {'returncode': code, 'output': data.decode('utf-8', errors='replace'), 'exception_info': None}
        except (TimeoutError, ValueError) as error:
            result = {'returncode': 125, 'output': type(error).__name__, 'exception_info': None}
        raw_output = result['output']
        if len(raw_output.encode()) > 4000:
            result['output'] = raw_output.encode()[:4000].decode('utf-8', errors='replace') + '\n[truncated]\n'
            result['truncated'] = True
        self.events.append({'command': command, 'result': result, 'elapsed': time.monotonic() - started})
        with (self.directory / 'executions.jsonl').open('a') as stream:
            stream.write(json.dumps(self.events[-1]) + '\n')
        return result

    def snapshot(self, destination):
        subprocess.run(['docker', 'pause', self.container_id], check=True, capture_output=True, timeout=15)
        code, data = bounded_process(['docker', 'cp', self.container_id + ':/workspace/.', '-'], 512 * 1024, 30)
        if code:
            raise RuntimeError('candidate archive failed')
        files = {}
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive:
                name = member.name[2:] if member.name.startswith('./') else member.name
                if name in ('.', '') and member.isdir():
                    continue
                if name not in self.protocol.WHITELIST or not member.isfile() or member.size > 128 * 1024 or name in files:
                    raise ValueError('unexpected candidate member')
                files[name] = archive.extractfile(member).read()
        if set(files) != set(self.protocol.WHITELIST):
            raise ValueError('incomplete candidate')
        destination.mkdir()
        for name, data in files.items():
            (destination / name).write_bytes(data)

    def close(self):
        if self.container_id:
            info = json.loads(subprocess.check_output(['docker', 'inspect', self.container_id], timeout=15))[0]
            if info['Config']['Labels'].get('venice-e2e-run') != self.nonce:
                raise ValueError('refusing foreign cleanup')
            subprocess.run(['docker', 'rm', '-f', self.container_id], check=True, capture_output=True, timeout=30)
            self.container_id = None
        if self.volume_name:
            info = json.loads(subprocess.check_output(['docker', 'volume', 'inspect', self.volume_name], timeout=15))[0]
            if info['Labels'].get('venice-e2e-run') != self.nonce:
                raise ValueError('refusing foreign volume cleanup')
            subprocess.run(['docker', 'volume', 'rm', self.volume_name], check=True, capture_output=True, timeout=30)
            self.volume_name = None


def apply_continuation_policy(facts, round_number, force_once=False):
    facts['real_accepted'] = facts['accepted']
    facts['continue'] = (not facts['accepted']) and facts.get('consecutive_no_progress', 0) < 2
    if force_once and round_number == 0:
        facts['forced_rejection'] = True
        facts['accepted'] = False
        facts['continue'] = True
        facts['required_action'] = ('External continuation check only. Keep a correct fix, '
                                    'do not revert passing code, rerun the read-only reproduction, and finish.')
    return facts


def sdk_acceptance(environment, directory, round_number):
    protocol = environment.protocol
    snapshot = pathlib.Path(os.environ['AUTONOMY_SNAPSHOT'])
    candidate = directory / ('round-' + str(round_number) + '-candidate')
    try:
        environment.snapshot(candidate)
    finally:
        subprocess.run(['docker', 'unpause', environment.container_id], capture_output=True, check=True, timeout=15)
    verdict = protocol.grade_candidate_container('docker', environment.image, snapshot, candidate)

    def comments(path):
        return collections.Counter(token.string for token in tokenize.generate_tokens(io.StringIO(path.read_text()).readline) if token.type == tokenize.COMMENT)

    added = comments(candidate / 'main.py') - comments(snapshot / 'agent' / 'main.py')
    current = hashlib.sha256((candidate / 'main.py').read_bytes()).hexdigest()
    source = pathlib.Path(os.environ['AUTONOMY_SOURCE_CANDIDATE']) if os.getenv('AUTONOMY_SOURCE_CANDIDATE') else snapshot / 'agent'
    previous = getattr(environment, 'last_candidate_hash', hashlib.sha256((source / 'main.py').read_bytes()).hexdigest())
    environment.no_progress = getattr(environment, 'no_progress', 0) + 1 if current == previous else 0
    environment.last_candidate_hash = current
    facts = {
        'round': round_number,
        'accepted': bool(verdict.get('passed')) and not added,
        'no_added_comments': not bool(added),
        'candidate_sha256': current,
        'consecutive_no_progress': environment.no_progress,
    }
    apply_continuation_policy(facts, round_number, os.getenv('AUTONOMY_FORCE_CONTINUE_ONCE') == '1')
    with (directory / 'acceptance-rounds.jsonl').open('a') as stream:
        stream.write(json.dumps(facts) + '\n')
    return facts


def task_prompt():
    prompt = (
        'Fix two real historical regressions in this venice-api snapshot. Work in /workspace. '
        'Python and the required dependencies are installed; there is no network. '
        'Edit ONLY the bodies of BrowserSession._answer and BrowserSession._generate_on_page in main.py. '
        'Do not change agent_protocol.py or any other code, add comments, or leave extra files. '
        'A missing assistant source must remain pending, not raise on None.strip(); literal marker-like '
        'assistant text is valid text. Preserve source failures as failures. Use inline python checks. '
        'When the SDK turn is complete, finish through the normal completion mechanism.'
    )
    visible = os.getenv('AUTONOMY_VISIBLE_REPRO')
    if visible:
        prompt += '\nA read-only reproduction is at /opt/repro.py. Run it before and after the edit. Do not modify it.\n'
    return prompt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-wiring', action='store_true')
    args = parser.parse_args(argv)
    if args.check_wiring:
        import inspect
        attempt = load_local('attempt')
        source = inspect.getsource(invoke_openhands)
        if 'exec(' in source or 'acceptance=acceptance' not in source:
            raise SystemExit('openhands adapter is not wired to continue_openhands')
        if 'continue_openhands' not in inspect.getsource(attempt.run_openhands):
            raise SystemExit('run_openhands does not call continue_openhands')
        print('wiring-ok')
        return 0
    if os.getenv('AUTONOMY_EXTERNAL_WATCHDOG') != '1':
        raise RuntimeError('external process watchdog is required')
    protocol = load_protocol()
    output_root = require_path('AUTONOMY_OUTPUT_ROOT')
    snapshot = require_path('AUTONOMY_SNAPSHOT')
    image = os.environ.get('AUTONOMY_WORKER_IMAGE', '').strip()
    if not image:
        raise RuntimeError('AUTONOMY_WORKER_IMAGE is required')
    protocol.PILOT_LABEL = 'venice-e2e-run=' + os.environ['AUTONOMY_RUN_NONCE']
    protocol.verify_snapshot(snapshot)
    attempt = load_local('attempt')
    started = time.time()
    directory = output_root / ('live-' + time.strftime('%Y%m%d-%H%M%S'))
    directory.mkdir()
    base_url, key = attempt.provider_settings()
    summary = {
        'task': 'historical venice-api repository regression',
        'engine': 'openhands',
        'adapter': 'repository_runner.invoke_openhands',
        'model': 'litellm/venice-deepseek',
        'accepted': False,
        'clean_finish': False,
        'image': image,
    }
    environment = None

    def deadline(*_):
        raise TimeoutError('external end-to-end deadline exceeded')

    signal.signal(signal.SIGALRM, deadline)
    remaining = float(os.environ['AUTONOMY_DEADLINE']) - time.time()
    if remaining <= 0:
        raise TimeoutError('deadline already passed')
    signal.alarm(int(remaining))
    try:
        environment = RepositoryEnvironment(snapshot, directory / 'agent', image, protocol)
        prompt = task_prompt()
        if os.getenv('AUTONOMY_VISIBLE_REPRO'):
            expected = hashlib.sha256(pathlib.Path(os.environ['AUTONOMY_VISIBLE_REPRO']).read_bytes()).hexdigest()
            check = environment.execute({'command': 'test -r /opt/repro.py && test ! -w /opt/repro.py && sha256sum /opt/repro.py'})
            if check['returncode'] != 0 or not check['output'].startswith(expected):
                raise RuntimeError('visible reproduction check failed')
            summary['visible_reproducer_sha256'] = expected
        try:
            result = invoke_openhands(attempt, environment, directory, prompt, base_url, key, sdk_acceptance)
            summary.update(result)
            summary['clean_finish'] = result.get('exit_status') == 'ConversationExecutionStatus.FINISHED' and 'run_error' not in summary
        except Exception as error:
            attempt.record_exception(summary, error, key, 'run_error')
            summary['clean_finish'] = False
        candidate = directory / 'candidate'
        environment.snapshot(candidate)
        subprocess.run(['docker', 'unpause', environment.container_id], capture_output=True, timeout=15)
        environment.close()
        summary['agent_commands'] = len(environment.events)
        summary['verdict'] = protocol.grade_candidate_container('docker', image, snapshot, candidate)
        summary['accepted'] = bool(summary['verdict'].get('passed'))
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        load_local('attempt').record_exception(summary, error, key, 'infrastructure_error')
        summary['clean_finish'] = False
    finally:
        signal.alarm(0)
        if environment is not None and environment.container_id:
            try:
                environment.close()
            except Exception as error:
                summary['cleanup_error_type'] = type(error).__name__
        summary['elapsed_seconds'] = round(time.time() - started, 3)
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2))
        public = {name: summary.get(name) for name in (
            'accepted', 'clean_finish', 'exit_status', 'elapsed_seconds', 'adapter', 'run_error_type', 'infrastructure_error_type', 'cleanup_error_type')}
        public['directory'] = directory.name
        print(json.dumps(public), flush=True)
    return 0 if summary.get('accepted') and summary.get('clean_finish') and not summary.get('cleanup_error_type') and not summary.get('run_error') else 1


if __name__ == '__main__':
    sys.exit(main())
