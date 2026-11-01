"""Validate an isolated normalized historical block with stock production Thanos."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tarfile
import time
import urllib.parse
import urllib.request

PINNED_THANOS = 'e88cf130a15f91ba8437885231fd3aa27fe88ef118b1fa2f2251465a526c7df9'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def query(selector, timestamp):
    seconds = str(timestamp // 1000) + '.' + str(timestamp % 1000).zfill(3)
    parameters = urllib.parse.urlencode({'query': selector, 'time': seconds,
                                        'max_source_resolution': '0s', 'partial_response': 'false', 'dedup': 'false'})
    with urllib.request.urlopen('http://127.0.0.1:19993/api/v1/query?' + parameters, timeout=30) as response:
        data = json.load(response)
    if data.get('status') != 'success' or data.get('warnings'):
        raise ValueError('Native raw query failed or returned partial data')
    return data['data']['result']


def run(root, stage):
    if os.geteuid() != 0 or root.is_symlink() or root.parent != Path('/var/tmp') or not root.name.startswith('otel-history-native-compat-'):
        raise ValueError('Isolated root-owned native compatibility workspace required')
    stat = root.lstat()
    if stat.st_uid != 0 or stat.st_mode & 0o077:
        raise ValueError('Native validation workspace must be root-only')
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    if int(memory['MemAvailable'].split()[0]) * 1024 < 2560 * 2**20:
        raise ValueError('Native compatibility memory reserve is insufficient')
    for port in (19991, 19992, 19993, 19994):
        with socket.socket() as handle:
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            handle.bind(('127.0.0.1', port))
    request = json.loads((root / 'request.json').read_text())
    if (root / 'bucket').exists():
        raise ValueError('Existing native compatibility output requires inspection')
    archive = stage / 'candidate.tar'
    if archive.stat().st_size != request['archiveBytes'] or sha(archive) != request['archiveSHA256']:
        raise ValueError('Transferred native block differs from verified controller archive')
    shutil.copyfile(stage / 'thanos', root / 'thanos')
    exe = root / 'thanos'
    if sha(exe) != PINNED_THANOS or request['nativeBinarySHA256'] != PINNED_THANOS:
        raise ValueError('Native verifier differs from pinned production executable')
    exe.chmod(0o700)
    disk = shutil.disk_usage(root)
    if disk.free - request['archiveBytes'] * 2 < disk.total // 5:
        raise ValueError('Native verification would breach 20% disk reserve')
    bucket = root / 'bucket'
    bucket.mkdir(mode=0o700)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != request['block'] or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe historical block archive member')
        tar.extractall(bucket, filter='data')
    config = root / 'objstore.json'
    config.write_text(json.dumps({'type': 'FILESYSTEM', 'config': {'directory': str(bucket)}}))
    children = []
    checks = []
    with (root / 'native.log').open('x') as log:
        try:
            subprocess.run([str(exe), 'tools', 'bucket', 'verify', '--objstore.config-file=' + str(config), '--issues=index_known_issues'],
                           stdout=log, stderr=log, check=True, timeout=900)
            commands = [
                ['store', '--objstore.config-file=' + str(config), '--data-dir=' + str(root / 'store-cache'), '--consistency-delay=0s',
                 '--grpc-address=127.0.0.1:19991', '--http-address=127.0.0.1:19992'],
                ['query', '--endpoint=127.0.0.1:19991', '--grpc-address=127.0.0.1:19994', '--http-address=127.0.0.1:19993', '--query.timeout=20s']]
            for arguments in commands:
                children.append(subprocess.Popen([str(exe)] + arguments, stdout=log, stderr=log,
                                env={**os.environ, 'GOMEMLIMIT': '512MiB', 'GOMAXPROCS': '1'}))
            deadline = time.monotonic() + 120
            for anchor in request['anchors']:
                while True:
                    if any(child.poll() is not None for child in children):
                        raise RuntimeError('Native Store/Query stopped unexpectedly')
                    try:
                        result = query(anchor['selector'], anchor['timestampMilliseconds'])
                        if len(result) == 1:
                            break
                    except (OSError, ValueError):
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError('Native Store did not expose the exact historical series')
                    time.sleep(1)
                point = result[0]
                if point['metric'] != anchor['labels']:
                    raise ValueError('Native external or ordinary historical labels differ')
                if struct.pack('>d', float(point['value'][1])).hex() != anchor['valueBits']:
                    raise ValueError('Native historical float bits differ')
                timestamp = query('timestamp(' + anchor['selector'] + ')', anchor['timestampMilliseconds'])
                if len(timestamp) != 1 or abs(float(timestamp[0]['value'][1]) * 1000 - anchor['timestampMilliseconds']) > 0.25:
                    raise ValueError('Native historical timestamp differs')
                checks.append({'metric': anchor['labels']['__name__'], 'exactLabelsAndFloatBitsVerified': True, 'timestampVerified': True})
            result = {'verified': True, 'productionModified': False, 'nativeThanosVersion': '0.42.4', 'nativeBinarySHA256': PINNED_THANOS,
                      'block': request['block'], 'archiveSHA256Verified': True, 'nativeIndexIssueVerificationPassed': True,
                      'anchorChecks': checks, 'completeCanonicalVerificationReplaced': False, 'servedWithOriginals': False}
            (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
            return result
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--stage', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.directory, args.stage)))
