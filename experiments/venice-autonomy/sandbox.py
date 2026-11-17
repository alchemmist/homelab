import io
import json
import os
import pathlib
import selectors
import shlex
import subprocess
import tarfile
import time
import uuid

IMAGE = 'docker.io/library/node@sha256:1f70dfa8d7be2321da1247e671217c11a555cd005edf4ccb014af28c9e8f78ca'
MAX_ARCHIVE = 2 * 1024 * 1024
MAX_FILE = 65536
MAX_OUTPUT = 24000


def bounded_process(args, limit, timeout=55):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('subprocess deadline exceeded')
            for key, _ in selector.select(min(remaining, 1)):
                part = os.read(key.fileobj.fileno(), 65536)
                if not part:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(part)
                if len(output) > limit:
                    raise ValueError('subprocess output limit exceeded')
        return process.wait(timeout=max(1, deadline-time.monotonic())), bytes(output)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def inspect_archive(data):
    result = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        for member in archive:
            path = pathlib.PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('unsafe archive path')
            if member.isdir() and str(path) == '.':
                continue
            if str(path) not in ('lib.cjs', 'test.cjs') or not member.isfile():
                raise ValueError('unexpected workspace entry or file type')
            if member.size > MAX_FILE or str(path) in result:
                raise ValueError('oversized or duplicate workspace entry')
            result[str(path)] = archive.extractfile(member).read().decode('utf-8')
    if set(result) != {'lib.cjs', 'test.cjs'}:
        raise ValueError('workspace is missing expected files')
    return result


class Sandbox:
    def __init__(self, files, directory, verifier=False):
        self.directory = pathlib.Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.events = []
        self.container_id = None
        self.volume_name = 'venice-lab-' + uuid.uuid4().hex[:12]
        self.verifier = verifier
        self.config = {'image': IMAGE, 'network': 'none', 'read_only': True}
        source = self.directory / 'input'
        source.mkdir()
        source.chmod(0o777)
        for name, content in files.items():
            if name not in ('lib.cjs', 'test.cjs'):
                raise ValueError('unexpected fixture path')
            path = source / name
            path.write_text(content)
            path.chmod(0o444 if verifier else 0o666)
        name = 'venice-lab-' + uuid.uuid4().hex[:12]
        run_key = str(self.directory.resolve())
        arguments = ['docker', 'run', '-d', '--name', name, '--label', 'venice-autonomy-lab=true',
                     '--label', 'venice-autonomy-run=' + run_key,
                     '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                     '--security-opt', 'no-new-privileges', '--pids-limit', '128',
                     '--memory', '512m', '--cpus', '1', '--user', '1000:1000',
                     '--tmpfs', '/tmp:rw,nosuid,noexec,size=64m', '--volume',
                     f'{self.volume_name}:/workspace:Z', '-w', '/workspace',
                     '-e', 'HOME=/tmp', '-e', 'GIT_CONFIG_NOSYSTEM=1', IMAGE, 'sleep', '35m']
        try:
            subprocess.run(['docker', 'volume', 'create', '--driver', 'local', '--opt', 'type=tmpfs',
                            '--opt', 'device=tmpfs', '--opt', 'o=size=32m,mode=0777',
                            '--label', 'venice-autonomy-lab=true', '--label', 'venice-autonomy-run=' + run_key,
                            self.volume_name],
                           capture_output=True, check=True, timeout=30)
            (self.directory / 'volume-name').write_text(self.volume_name)
            self.container_id = subprocess.check_output(arguments, text=True, timeout=45).strip()
            (self.directory / 'container-id').write_text(self.container_id)
            subprocess.run(['docker', 'cp', str(source) + '/.', self.container_id + ':/workspace'],
                           capture_output=True, check=True, timeout=30)
            self.security = self.inspect_security()
            capacity_probe = ("const s=require('node:fs').statfsSync('/workspace');"
                              "if(s.type!==0x01021994||s.bsize*s.blocks!==33554432)process.exit(1);"
                              "console.log('CAPACITY_OK')")
            code, output = bounded_process(['docker', 'exec', self.container_id, 'node', '-e', capacity_probe], 2048, 15)
            if code != 0 or output.strip() != b'CAPACITY_OK':
                raise ValueError('workspace tmpfs capacity preflight failed')
            self.security['workspace_capacity_bytes'] = 33554432
            if not verifier:
                probe = ("const f=require('node:fs');const fd=f.openSync('/workspace/lib.cjs','r+');"
                         "f.closeSync(fd);f.writeFileSync('/workspace/.lab-preflight','ok');"
                         "f.unlinkSync('/workspace/.lab-preflight');console.log('WORKSPACE_WRITE_OK')")
                code, output = bounded_process(['docker', 'exec', self.container_id, 'node', '-e', probe], 2048, 15)
                if code != 0 or output.strip() != b'WORKSPACE_WRITE_OK':
                    raise ValueError('workspace write preflight failed')
            (self.directory / 'security.json').write_text(json.dumps(self.security, indent=2))
        except BaseException:
            self.close()
            raise

    def inspect_security(self):
        info = json.loads(subprocess.check_output(['docker', 'inspect', self.container_id], timeout=15))[0]
        config, host = info['Config'], info['HostConfig']
        result = {'network': host['NetworkMode'], 'read_only': host['ReadonlyRootfs'],
                  'user': config['User'], 'bind_mounts': info['Mounts'],
                  'cap_drop': host['CapDrop'], 'security_opt': host['SecurityOpt'],
                  'memory': host['Memory'], 'pids_limit': host['PidsLimit'],
                  'environment_names': [value.split('=', 1)[0] for value in config['Env']]}
        code, kernel = bounded_process(['docker', 'exec', self.container_id, 'bash', '-lc',
                                        "grep -E '^(Cap(Inh|Prm|Eff|Bnd|Amb)|NoNewPrivs):' /proc/self/status"], 2048, 15)
        result['kernel_security'] = kernel.decode('ascii')
        kernel_values = dict(line.split(':', 1) for line in result['kernel_security'].splitlines())
        kernel_ok = (code == 0 and kernel_values.get('NoNewPrivs', '').strip() == '1' and
                     all(int(kernel_values.get(name, '1').strip(), 16) == 0
                         for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')))
        (self.directory / 'security.json').write_text(json.dumps(result, indent=2))
        if (not kernel_ok or result['network'] != 'none' or not result['read_only'] or
                result['user'] != '1000:1000' or
                len(result['bind_mounts']) != 1 or
                result['bind_mounts'][0].get('Type') != 'volume' or
                result['bind_mounts'][0].get('Name') != self.volume_name or
                result['bind_mounts'][0].get('Destination') != '/workspace' or
                result['memory'] != 512 * 1024 * 1024 or result['pids_limit'] != 128 or
                not any(value.startswith('no-new-privileges') for value in result['security_opt']) or
                any('KEY' in name or 'TOKEN' in name for name in result['environment_names'])):
            raise ValueError('sandbox security preflight failed')
        return result

    def execute(self, action, **kwargs):
        command = action['command']
        wrapped = ('timeout -k 2 40 bash -lc ' + shlex.quote(command) +
                   ' 2>&1 | head -c ' + str(MAX_OUTPUT) + '; status=${PIPESTATUS[0]}; exit "$status"')
        started = time.time()
        code, output = bounded_process(['docker', 'exec', '-w', '/workspace', self.container_id,
                                        'bash', '-lc', wrapped], MAX_OUTPUT, timeout=50)
        text = output.decode('utf-8', errors='replace')
        event = {'command': command, 'returncode': code, 'output': text,
                 'started': started, 'elapsed': round(time.time()-started, 3), 'verifier': self.verifier}
        self.events.append(event)
        with (self.directory / 'executions.jsonl').open('a') as stream:
            stream.write(json.dumps(event) + '\n')
        return {'returncode': code, 'output': text, 'exception_info': None}

    def snapshot(self):
        subprocess.run(['docker', 'pause', self.container_id], capture_output=True, check=True, timeout=15)
        code, data = bounded_process(['docker', 'cp', self.container_id + ':/workspace/.', '-'],
                                     MAX_ARCHIVE, timeout=30)
        if code:
            raise ValueError('workspace snapshot failed')
        return inspect_archive(data)

    def get_template_vars(self):
        return {'cwd': '/workspace', **self.config}

    def serialize(self):
        return {'info': {'environment': self.config, 'security': self.security}}

    def close(self):
        import owned_resources
        expected = str(self.directory.resolve())
        errors = []
        if self.container_id:
            try:
                owned_resources.remove_container(self.container_id, expected)
            except Exception as error:
                errors.append(str(error))
            else:
                self.container_id = None
        if self.volume_name:
            try:
                owned_resources.remove_volume(self.volume_name, expected)
            except Exception as error:
                errors.append(str(error))
            else:
                self.volume_name = None
        if errors:
            raise ValueError('; '.join(errors))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
