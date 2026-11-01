"""Preserve a fixed legacy tail before background compaction changes block IDs.

Read-only production source access. A capture is not a canonical certification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import tarfile


def files(root):
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlinked legacy source rejected')
        if path.is_file():
            stat = path.stat()
            result[str(path.relative_to(root))] = [stat.st_ino, stat.st_size, stat.st_mtime_ns]
    return result


def capture(manifest, output):
    os.umask(0o077)
    if os.geteuid() != 0 or output.exists() or output.parent != Path('/home/alchemmist') or not output.name.startswith('otel-history-cutover-tail-'):
        raise ValueError('New owned private capture destination required')
    scope = json.loads(manifest.read_text())
    if scope.get('productionPublicationApproved') is not False or not scope.get('blocks'):
        raise ValueError('Explicit read-only frozen source scope required')
    snapshots = {}
    for expected in scope['blocks']:
        name = expected['ulid']
        if not re.fullmatch(r'[0-9A-HJKMNP-TV-Z]{26}', name) or name in snapshots:
            raise ValueError('Unsafe or duplicate original block identity')
        source = Path('/var/lib/socrat-thanos') / name
        if source.is_symlink():
            raise ValueError('Symlinked source block rejected')
        meta = json.loads((source / 'meta.json').read_text())
        for key in ['ulid', 'minTime', 'maxTime', 'stats', 'compaction']:
            if meta.get(key) != expected.get(key):
                raise ValueError('Frozen source semantic identity changed')
        if meta.get('thanos', {}).get('downsample', {}).get('resolution', 0) != 0 or meta.get('thanos', {}).get('labels', {}) != expected['externalLabels']:
            raise ValueError('Unexpected resolution or external context')
        snapshots[name] = files(source)
    size = sum(item[1] for snapshot in snapshots.values() for item in snapshot.values())
    disk = shutil.disk_usage('/var/lib/socrat-thanos')
    if size > 24 * 1024**3 or disk.free - size * 2 < disk.total // 5:
        raise ValueError('Frozen source capture would breach bounded disk budget')
    output.mkdir(mode=0o700)
    archive = output / 'legacy-tail.tar'
    with tarfile.open(archive, 'x') as tar:
        for name in snapshots:
            tar.add(Path('/var/lib/socrat-thanos') / name, arcname=name)
    for name, before in snapshots.items():
        if files(Path('/var/lib/socrat-thanos') / name) != before:
            raise ValueError('Original changed during immutable capture')
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    receipt = {'captured': True, 'originalFilesUnchanged': True, 'productionModified': False,
               'canonicalVerificationStillRequired': True, 'archiveSHA256': digest,
               'archiveBytes': archive.stat().st_size, 'blocks': scope['blocks'],
               'samples': sum(block['stats']['numSamples'] for block in scope['blocks'])}
    result = output / 'capture.json'
    result.write_text(json.dumps(receipt, indent=2) + '\n')
    owner = pwd.getpwnam('alchemmist')
    for path in [archive, result, output]:
        os.chown(path, owner.pw_uid, owner.pw_gid)
    print(json.dumps({'capturedBlocks': len(snapshots), 'capturedSamples': receipt['samples'], 'productionModified': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    capture(args.manifest, args.output)
