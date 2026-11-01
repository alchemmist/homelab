"""Read-only preserved capture of the already approved live repaired raw block.

The archive is NOT trusted as recovered data until healthy-host inventory equals
its previously verified 6,383,043,932-sample canonical SHA256. No new loss allowed.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import tarfile

SOURCE = Path('/var/lib/socrat-thanos/01M66BZJJH7AX3HTZFRZD02SXP')
OUTPUT = Path('/home/alchemmist/otel-live-repaired-20261031')
EXPECTED = '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209'


def inventory(root):
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink in immutable original block')
        if path.is_file():
            stat = path.stat()
            result[str(path.relative_to(root))] = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
    return result


def run():
    os.umask(0o077)
    if os.geteuid() != 0 or SOURCE.is_symlink() or OUTPUT.exists():
        raise ValueError('Root read-only original capture and new private output required')
    meta = json.loads((SOURCE / 'meta.json').read_text())
    if meta['ulid'] != SOURCE.name or meta['stats']['numSamples'] != 6383043932:
        raise ValueError('Live repaired source identity changed')
    before = inventory(SOURCE)
    disk = shutil.disk_usage(SOURCE)
    size = sum(item[1] for item in before.values())
    if disk.free - size * 2 < disk.total // 5:
        raise ValueError('Preserved capture violates 20% disk reserve')
    OUTPUT.mkdir(mode=0o700, parents=True)
    archive = OUTPUT / 'candidate.tar'
    with tarfile.open(archive, 'x') as tar:
        tar.add(SOURCE, arcname=SOURCE.name)
    if inventory(SOURCE) != before:
        raise ValueError('Original block changed during immutable capture')
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    receipt = {'captured': True, 'archiveSHA256': digest, 'archiveBytes': archive.stat().st_size,
               'sourceULID': SOURCE.name, 'expectedSamples': 6383043932, 'expectedCanonicalSHA256': EXPECTED,
               'originalFilesUnchanged': True, 'healthyHostCanonicalVerificationStillRequired': True,
               'productionModified': False, 'additionalLossApproved': False}
    result = OUTPUT / 'capture.json'
    result.write_text(json.dumps(receipt, indent=2) + '\n')
    account = pwd.getpwnam('alchemmist')
    for path in [archive, result, OUTPUT]:
        os.chown(path, account.pw_uid, account.pw_gid)
    archive.chmod(0o600)
    result.chmod(0o600)
    print(json.dumps({'captured': True, 'originalFilesUnchanged': True, 'productionModified': False}))


if __name__ == '__main__':
    run()
