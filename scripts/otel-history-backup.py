import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = 'cattle-monitoring-system'
PROMETHEUS = 'kube-prometheus-stack-prometheus'
COMPACTORS = ['thanos-compactor', 'thanos-compactor-5m', 'thanos-compactor-1h']
ARCHIVER = ROOT / 'scripts/otel-history-archive.py'


def command(arguments, timeout=180, **kwargs):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, **kwargs)
    if result.returncode:
        raise RuntimeError(f'Command failed: {arguments[0]} (exit {result.returncode}): {result.stderr[-1500:]}')
    return result.stdout


def ssh(host, arguments, **kwargs):
    return command(['ssh', '-o', 'BatchMode=yes', host, shlex.join(arguments)], **kwargs)


def kube(host, *arguments, **kwargs):
    return ssh(host, ['kubectl', '-n', NAMESPACE, *arguments], **kwargs)


def get(host, resource, name):
    return json.loads(kube(host, 'get', resource, name, '-o', 'json'))


def patch(host, resource, name, value):
    kube(host, 'patch', resource, name, '--type=merge', '-p', json.dumps(value))


def save(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def wait_for(predicate, description, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(2)
    raise RuntimeError('Timed out: ' + description)


def prometheus_ready(host, admin):
    try:
        pod = get(host, 'pod', 'prometheus-' + PROMETHEUS + '-0')
        container = next(item for item in pod['spec']['containers'] if item['name'] == 'prometheus')
        enabled = '--web.enable-admin-api' in container.get('args', [])
        ready = any(item['type'] == 'Ready' and item['status'] == 'True' for item in pod.get('status', {}).get('conditions', []))
        return enabled == admin and ready and not pod['metadata'].get('deletionTimestamp')
    except (RuntimeError, StopIteration):
        return False


def archive_from_pod(host, pod, source, destination, node, run):
    uid = int(ssh(node, ['id', '-u']).strip())
    stage = '/textfile/otel-history-backup/' + run
    filename = destination.name
    access = """import os, struct
def grant(path, uid, directory=False):
    owner, user = (7, 5) if directory else (6, 4)
    entries = [(1, owner, 4294967295), (2, user, uid), (4, 0, 4294967295), (16, user, 4294967295), (32, 0, 4294967295)]
    data = struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in entries)
    os.setxattr(path, 'system.posix_acl_access', data)
"""
    worker = """import gzip, hashlib, json, os, pathlib, sys
namespace = {'__name__': 'archive_module'}
exec(ARCHIVER_SOURCE, namespace)
output = pathlib.Path(STAGE) / FILENAME
result = output.with_name(output.name + '.result.json')
try:
    with gzip.open(str(output) + '.partial', 'xb', compresslevel=1) as stream:
        namespace['pack'](pathlib.Path(SOURCE), stream)
    with gzip.open(str(output) + '.partial', 'rb') as stream:
        report = namespace['verify'](stream)
    digest = hashlib.sha256()
    with open(str(output) + '.partial', 'rb') as stream:
        while data := stream.read(4 * 1024 ** 2):
            digest.update(data)
    os.chmod(str(output) + '.partial', 0o600)
    grant(str(output) + '.partial', UID)
    os.rename(str(output) + '.partial', output)
    data = {'success': True, 'sha256': digest.hexdigest(), 'report': report}
except Exception as error:
    data = {'success': False, 'error': str(error)}
with result.open('x') as stream:
    json.dump(data, stream)
os.chmod(result, 0o600)
grant(result, UID)
"""
    bindings = {'ARCHIVER_SOURCE': ARCHIVER.read_text(), 'STAGE': stage,
                'FILENAME': filename, 'SOURCE': source, 'UID': uid}
    worker = '\n'.join(key + ' = ' + repr(value) for key, value in bindings.items()) + '\n' + access + '\n' + worker
    launcher = """import os, pathlib, subprocess, sys
stage = pathlib.Path(STAGE)
for directory in (stage.parent, stage):
    directory.mkdir(mode=0o700, exist_ok=True)
    grant(directory, UID, directory=True)
log = stage / (FILENAME + '.log')
with log.open('xb') as stream:
    os.chmod(log, 0o600)
    grant(log, UID)
    subprocess.Popen([sys.executable, '-c', WORKER], stdin=subprocess.DEVNULL,
                     stdout=stream, stderr=stream, start_new_session=True)
print('started')
"""
    launcher_bindings = {'STAGE': stage, 'FILENAME': filename, 'UID': uid, 'WORKER': worker}
    launcher = '\n'.join(key + ' = ' + repr(value) for key, value in launcher_bindings.items()) + '\n' + access + '\n' + launcher
    kube(host, 'exec', pod, '--', 'python3', '-c', launcher)
    host_path = '/var/lib/node_exporter/textfile_collector/otel-history-backup/' + run + '/' + filename
    poll = """import json, pathlib, time
path = pathlib.Path(PATH)
deadline = time.monotonic() + 1500
while not path.exists():
    if time.monotonic() > deadline:
        raise TimeoutError('archive worker did not finish')
    time.sleep(2)
print(path.read_text())
"""
    poll = 'PATH = ' + repr(host_path + '.result.json') + '\n' + poll
    result = json.loads(ssh(node, ['python3', '-c', poll], timeout=1600))
    if not result['success']:
        raise RuntimeError('Archive preparation failed: ' + result['error'])
    command(['scp', '-q', node + ':' + host_path, str(destination)], timeout=1800)
    os.chmod(destination, 0o600)
    save(destination.with_name(filename + '.source-verification.json'), result)


def stop_signal(signum, frame):
    raise KeyboardInterrupt(f'Signal {signum}')


def backup(host, destination, replica_host):
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(destination, 0o700)
    lock = 'otel-history-backup-lock'
    kube(host, 'create', 'configmap', lock, '--from-literal=run=' + destination.name)
    acquired = True
    state = None
    restored = False
    try:
        prometheus = get(host, 'prometheus', PROMETHEUS)
        cron = get(host, 'cronjob', 'thanos-cascade')
        deployments = {name: get(host, 'deployment', name) for name in COMPACTORS}
        state = {
            'schemaVersion': 1, 'createdAt': datetime.now(timezone.utc).isoformat(),
            'controlHost': host, 'prometheusAdmin': prometheus['spec'].get('enableAdminAPI', False),
            'cascadeSuspended': cron['spec'].get('suspend', False),
            'compactorReplicas': {name: item['spec'].get('replicas', 1) for name, item in deployments.items()},
        }
        save(destination / 'restore-state.json', state)
        pods = json.loads(kube(host, 'get', 'pods', '-l', 'app=thanos-disk', '-o', 'json'))['items']
        disk_pods = {pod['spec']['nodeName']: pod['metadata']['name'] for pod in pods}
        volumes = json.loads(kube(host, 'get', 'pv', '-o', 'json'))['items']
        pv = next(item for item in volumes if item['spec'].get('claimRef', {}).get('name', '') == 'prometheus-' + PROMETHEUS + '-db-prometheus-' + PROMETHEUS + '-0')
        storage = pv['spec']['local']['path']
        if not storage.startswith('/var/lib/') or '..' in Path(storage).parts:
            raise ValueError('Unexpected Prometheus storage path')
        patch(host, 'cronjob', 'thanos-cascade', {'spec': {'suspend': True}})
        wait_for(lambda: not get(host, 'cronjob', 'thanos-cascade').get('status', {}).get('active'), 'cascade completion')
        for name in COMPACTORS:
            patch(host, 'deployment', name, {'spec': {'replicas': 0}})
        for name in COMPACTORS:
            wait_for(lambda name=name: not get(host, 'deployment', name).get('status', {}).get('replicas'), name + ' stopped')
        if not state['prometheusAdmin']:
            patch(host, 'prometheus', PROMETHEUS, {'spec': {'enableAdminAPI': True}})
        wait_for(lambda: prometheus_ready(host, True), 'temporary snapshot API readiness')
        path = '/api/v1/namespaces/' + NAMESPACE + '/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/admin/tsdb/snapshot?skip_head=false'
        response = json.loads(kube(host, 'create', '--raw', path, '-f', '-', input='{}'))
        if response.get('status') != 'success':
            raise RuntimeError('Prometheus snapshot failed')
        snapshot = response['data']['name']
        if '/' in snapshot or snapshot in ('', '.', '..'):
            raise ValueError('Invalid snapshot name')
        save(destination / 'snapshot.json', {'snapshot': snapshot, 'storage': storage, 'skipHead': False})
        sources = {
            'prometheus-snapshot': ('socrat-0', disk_pods['socrat-0'], '/host' + storage + '/prometheus-db/snapshots/' + snapshot),
            'thanos-raw': ('socrat-0', disk_pods['socrat-0'], '/host/var/lib/socrat-thanos'),
            'thanos-5m': ('socrat-1', disk_pods['socrat-1'], '/host/var/lib/socrat-thanos-5m'),
            'thanos-1h': ('socrat-3', disk_pods['socrat-3'], '/host/var/lib/socrat-thanos-1h'),
        }
        for name, (node, pod, source) in sources.items():
            print('Archiving ' + name, flush=True)
            archive_from_pod(host, pod, source, destination / (name + '.tar.gz'), node, destination.name)
    finally:
        errors = []
        if state is not None:
            actions = [
                ('prometheus', PROMETHEUS, {'spec': {'enableAdminAPI': state['prometheusAdmin']}}),
                *[('deployment', name, {'spec': {'replicas': replicas}}) for name, replicas in state['compactorReplicas'].items()],
                ('cronjob', 'thanos-cascade', {'spec': {'suspend': state['cascadeSuspended']}}),
            ]
            for resource, name, value in actions:
                try:
                    patch(host, resource, name, value)
                except Exception as error:
                    errors.append(str(error))
            try:
                wait_for(lambda: prometheus_ready(host, state['prometheusAdmin']), 'restored Prometheus readiness')
            except Exception as error:
                errors.append(str(error))
            for name, replicas in state['compactorReplicas'].items():
                if replicas:
                    try:
                        wait_for(lambda name=name, replicas=replicas: get(host, 'deployment', name).get('status', {}).get('availableReplicas', 0) >= replicas, name + ' restored')
                    except Exception as error:
                        errors.append(str(error))
        if acquired and not errors:
            kube(host, 'delete', 'configmap', lock)
            restored = True
        save(destination / 'restoration.json', {'restored': restored, 'errors': errors})
        if errors:
            raise RuntimeError('RESTORATION INCOMPLETE; keep lock and inspect restore-state.json: ' + '; '.join(errors))
    reports = {}
    for archive in sorted(destination.glob('*.tar.gz')):
        reports[archive.name] = json.loads(command(['python3', str(ARCHIVER), 'verify', '--archive', str(archive)]))
    if not reports.get('prometheus-snapshot.tar.gz', {}).get('blockCount'):
        raise RuntimeError('Snapshot has no blocks')
    save(destination / 'local-verification.json', reports)
    replicate(destination, replica_host)


def replicate(destination, replica_host):
    state = json.loads((destination / 'restoration.json').read_text())
    if not state.get('restored') or state.get('errors'):
        raise RuntimeError('Restore controller state before resuming replication')
    reports = json.loads((destination / 'local-verification.json').read_text())
    archive_hashes = {}
    for name in reports:
        archive = destination / name
        digest = hashlib.sha256()
        with archive.open('rb') as stream:
            while data := stream.read(4 * 1024 ** 2):
                digest.update(data)
        source = json.loads(archive.with_name(name + '.source-verification.json').read_text())
        archive_hashes[name] = source['sha256']
        if not source['success'] or digest.hexdigest() != source['sha256'] or source['report'] != reports[name]:
            raise RuntimeError('Local archive differs from the verified source')
    remote_directory = 'monitoring-backups/' + destination.name
    ssh(replica_host, ['mkdir', '-m', '700', '-p', 'monitoring-backups'])
    ssh(replica_host, ['mkdir', '-m', '700', '-p', remote_directory])
    command(['rsync', '-a', str(destination) + '/', replica_host + ':' + remote_directory + '/'], timeout=1800)
    command(['scp', '-q', str(ARCHIVER), replica_host + ':' + remote_directory + '/archive-verifier.py'])
    verified = {}
    for name in reports:
        verified[name] = json.loads(ssh(replica_host, ['python3', remote_directory + '/archive-verifier.py', 'verify', '--archive', remote_directory + '/' + name, '--expected-sha256', archive_hashes[name]], timeout=1800))
        if verified[name] != reports[name]:
            raise RuntimeError('Remote archive verification differs from local verification')
    save(destination / 'replica-verification.json', {'host': replica_host, 'directory': remote_directory, 'reports': verified, 'archiveSha256': archive_hashes})
    print(json.dumps({'verified': True, 'local': str(destination), 'replicaHost': replica_host, 'replicaDirectory': remote_directory}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-host', default='socrat-0')
    parser.add_argument('--replica-host', default='socrat-3')
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--resume-copy', action='store_true')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    try:
        if args.resume_copy:
            replicate(args.destination.resolve(), args.replica_host)
        else:
            backup(args.ssh_host, args.destination.resolve(), args.replica_host)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
