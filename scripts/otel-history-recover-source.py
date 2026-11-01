"""Recover one original raw block from the verified durable backup in one pass.

Unprivileged, bounded, no production writes. Extracted bytes remain untrusted
until the entire original compressed archive SHA256 and source stat match.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import time


def atomic(path, document):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(document, indent=2) + '\n')
    temporary.replace(path)


class HashReader:
    def __init__(self, stream, output):
        self.stream = stream
        self.output = output
        self.digest = hashlib.sha256()
        self.count = 0
        self.next_report = 64 * 1024**2

    def read(self, size=-1):
        value = self.stream.read(size)
        self.digest.update(value)
        self.count += len(value)
        if self.count >= self.next_report:
            atomic(self.output / 'progress.json', {'phase': 'verify-and-extract', 'compressedBytesRead': self.count, 'verified': False})
            self.next_report = self.count + 64 * 1024**2
        return value


def run(archive, block, expected, output):
    os.umask(0o077)
    if not re.fullmatch(r'[0-9A-HJKMNP-TV-Z]{26}', block) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Explicit source ULID and complete known archive SHA256 required')
    if archive.is_symlink() or output.exists():
        raise ValueError('Regular original archive and new isolated output required')
    disk = shutil.disk_usage(output.parent)
    maximum = 3 * 1024**3
    if disk.free - maximum * 2 < disk.total // 5:
        raise ValueError('Recovery would breach 20% filesystem reserve')
    output.mkdir(mode=0o700)
    source_stat = archive.stat()
    extracted = 0
    seen = set()
    report = {'verified': False, 'block': block, 'productionModified': False}
    try:
        with archive.open('rb') as stream:
            reader = HashReader(stream, output)
            with tarfile.open(fileobj=reader, mode='r|gz') as tar:
                for member in tar:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('Unsafe archive member')
                    if not path.parts or path.parts[0] != block:
                        continue
                    if not (member.isfile() or member.isdir()) or member.name in seen:
                        raise ValueError('Unsupported or duplicate source block member')
                    seen.add(member.name)
                    target = output / 'source' / Path(*path.parts)
                    if member.isdir():
                        target.mkdir(mode=0o700, parents=True, exist_ok=True)
                        continue
                    extracted += member.size
                    if extracted > maximum:
                        raise ValueError('Source block exceeds bounded recovery budget')
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with tar.extractfile(member) as incoming, target.open('xb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing, 1024**2)
                    if target.stat().st_size != member.size:
                        raise ValueError('Truncated source member')
            while reader.read(4 * 1024**2):
                pass
        after = archive.stat()
        if (source_stat.st_ino, source_stat.st_size, source_stat.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Original source changed during verification')
        if reader.digest.hexdigest() != expected:
            raise ValueError('Original durable archive SHA256 differs from approved backup')
        root = output / 'source' / block
        metadata = json.loads((root / 'meta.json').read_text())
        if metadata['ulid'] != block or not (root / 'index').is_file() or not any((root / 'chunks').iterdir()):
            raise ValueError('Recovered raw block is incomplete')
        if metadata.get('thanos', {}).get('downsample', {}).get('resolution', 0) != 0:
            raise ValueError('Only original raw source recovery is supported')
        report.update(verified=True, archiveSHA256=expected, originalArchiveUnchanged=True,
                      compressedBytesRead=reader.count, sourceBytes=extracted, sourceDirectory=str(root))
    except Exception as error:
        report['errorType'] = type(error).__name__
        raise
    finally:
        report['finishedAtUnix'] = time.time()
        atomic(output / 'result.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['archive', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--block', required=True)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    run(args.archive, args.block, args.expected_sha256, args.output)
