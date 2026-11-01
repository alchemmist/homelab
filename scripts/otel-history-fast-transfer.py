"""Sealed one-time replica of completed history and queued inputs onto socrat-0.

Never publishes, deletes originals, reads credentials or starts an importer.
Exact archive SHA and a fixed destination allowlist fence extraction.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import shutil
import socket
import tarfile

HOME = Path('/home/alchemmist')
STATE = Path('/var/lib/homelab-otel-history')
WORK = HOME / 'otel-history-current-roundtrip-work-20261031'
GOLDEN = HOME / '.local/share/homelab/otel-golden-sources-20261101'
INPUT = HOME / '.local/share/homelab/otel-tail-input-20261101'
TRANSFER = HOME / '.local/share/homelab/otel-fast-transfer-20261101'
CURRENT = STATE / 'current-roundtrip-20261031-v2'
FINAL = STATE / 'current-native-finalize-20261031'
TAIL = STATE / 'tail-roundtrip-20261101'
BLOCK = '01M6BBYTZHHWT579DX99J3S7EF'
CANONICAL = '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def roots():
    result = [CURRENT / 'result.json', WORK / 'restored' / BLOCK, WORK / 'otlp/manifest.json',
              STATE / 'coverage-20261031/target-integrity.json', GOLDEN / 'references.json', GOLDEN / 'receipts']
    result += [INPUT / name for name in ['capture.json', 'verification.json', 'legacy-tail.tar']]
    result += [FINAL / name for name in ['tools.json', 'anchors', 'thanos']]
    result += [TAIL / name for name in ['tools.json', 'anchors', 'thanos', 'otel-history']]
    return result


def allowed(member):
    path = PurePosixPath(member.name)
    if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):
        return False
    absolute = Path('/') / str(path)
    return any(absolute == root or absolute.is_relative_to(root) for root in roots())


def prepare():
    if socket.gethostname() != 'socrat-1':
        raise ValueError('Read-only source replica preparation belongs only on socrat-1')
    result = json.loads((CURRENT / 'result.json').read_text())
    if not (result.get('success') is True and result.get('fullCanonicalRoundtripVerified') is True
            and result['sourceSamples'] == 6383043932 and result['sourceCanonicalSHA256'] == CANONICAL
            and result['restoredBlock'] == str(WORK / 'restored' / BLOCK)):
        raise ValueError('Only completed exact current roundtrip may be copied')
    paths = roots()
    files = []
    for root in paths:
        if not root.exists() or root.is_symlink():
            raise ValueError('Immutable replica input missing or symlinked')
        for path in ([root] if root.is_file() else list(root.rglob('*'))):
            if path.is_symlink():raise ValueError('No source symlinks permitted')
            if path.is_file():files.append(path)
    needed = sum(path.stat().st_size for path in files) + 256 * 1024**2
    disk = shutil.disk_usage(STATE)
    if disk.free - needed < disk.total // 5:
        raise ValueError('Single sealed transfer archive would breach source reserve')
    TRANSFER.mkdir(mode=0o700)
    archive = TRANSFER / 'bundle.tar'
    with tarfile.open(archive, 'x') as target:
        for root in paths:target.add(root, arcname=str(root).lstrip('/'), recursive=True)
    receipt = {'success': True, 'sourceNode': 'socrat-1', 'destinationNode': 'socrat-0',
        'archiveSHA256': sha(archive), 'archiveBytes': archive.stat().st_size,
        'completedRoundtripSamples': 6383043932, 'completedRoundtripCanonicalSHA256': CANONICAL,
        'originalsDeleted': False, 'productionPublished': False, 'importerStarted': False}
    (TRANSFER / 'source-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    account = pwd.getpwnam('alchemmist')
    for path in [TRANSFER, archive, TRANSFER / 'source-receipt.json']:
        os.chown(path, account.pw_uid, account.pw_gid)
    archive.chmod(0o600)
    print(json.dumps(receipt))


def install(expected_sha):
    if socket.gethostname() != 'socrat-0':
        raise ValueError('Replica install belongs only on trusted socrat-0')
    archive = TRANSFER / 'bundle.tar'
    if archive.is_symlink() or sha(archive) != expected_sha:
        raise ValueError('Whole sealed transfer SHA differs')
    for root in roots():
        if root.exists():raise ValueError('Refuse to overwrite an existing destination')
        for parent in root.parents:
            if parent.is_symlink():raise ValueError('Destination ancestor is symlinked')
    disk = shutil.disk_usage('/var/lib')
    if disk.free - archive.stat().st_size * 3 < disk.total // 5:
        raise ValueError('Destination replica and native finalization reserve insufficient')
    with tarfile.open(archive, 'r:') as source:
        members = source.getmembers()
        if any(not allowed(member) for member in members):
            raise ValueError('Archive member outside explicit immutable replica allowlist')
        source.extractall('/', members=members, filter='data')
    result = json.loads((CURRENT / 'result.json').read_text())
    if not result['success'] or result['sourceCanonicalSHA256'] != CANONICAL:
        raise ValueError('Transferred canonical receipt differs')
    receipt = {'success': True, 'archiveSHA256': expected_sha, 'archiveBytes': archive.stat().st_size,
        'completedRoundtripReusedWithoutReimport': True, 'tailImporterStarted': False,
        'originalsDeleted': False, 'productionPublished': False, 'node': 'socrat-0'}
    (TRANSFER / 'destination-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'install'])
    parser.add_argument('--sha256')
    args = parser.parse_args()
    if os.geteuid() != 0:raise ValueError('Protected root-owned replica operation required')
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'importer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'prepare':prepare()
        else:
            if not args.sha256 or len(args.sha256) != 64:raise ValueError('Explicit sealed SHA required')
            install(args.sha256)
