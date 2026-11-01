"""Verify the off-node fixed-scope tar against its capture hash and metadata.

Not a native sample canonical certificate; keeps original and failed artifacts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile


class Reader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        self.count += len(data)
        return data


def run(root):
    os.umask(0o077)
    if (root / 'verification.json').exists():
        raise ValueError('Existing replica verification must not be overwritten')
    receipt = {'verified': False, 'productionModified': False, 'canonicalVerificationStillRequired': True}
    try:
        capture = json.loads((root / 'capture.json').read_text())
        expected = {block['ulid']: block for block in capture['blocks']}
        if len(expected) != len(capture['blocks']) or capture.get('originalFilesUnchanged') is not True:
            raise ValueError('Invalid fixed original capture manifest')
        archive = root / 'legacy-tail.tar'
        if archive.is_symlink() or archive.stat().st_size != capture['archiveBytes']:
            raise ValueError('Replica archive size differs')
        before = archive.stat()
        seen = set()
        metadata_seen = set()
        with archive.open('rb') as stream:
            reader = Reader(stream)
            with tarfile.open(fileobj=reader, mode='r|') as tar:
                for member in tar:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in expected or not (member.isfile() or member.isdir()) or member.name in seen:
                        raise ValueError('Unsafe or duplicate preserved-scope member')
                    seen.add(member.name)
                    if len(path.parts) == 2 and path.parts[1] == 'meta.json':
                        if member.size > 4 * 1024**2:
                            raise ValueError('Unexpectedly large native metadata')
                        actual = json.load(tar.extractfile(member))
                        original = expected[path.parts[0]]
                        for key in ['ulid', 'minTime', 'maxTime', 'stats', 'compaction']:
                            if actual.get(key) != original.get(key):
                                raise ValueError('Replica semantic metadata differs from frozen source')
                        if actual.get('thanos', {}).get('labels', {}) != original['externalLabels']:
                            raise ValueError('Replica external context differs')
                        metadata_seen.add(path.parts[0])
            while reader.read(4 * 1024**2):
                pass
        after = archive.stat()
        if metadata_seen != set(expected) or reader.digest.hexdigest() != capture['archiveSHA256'] or reader.count != capture['archiveBytes']:
            raise ValueError('Whole archive SHA256 or declared block coverage differs')
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Replica archive changed while verifying')
        receipt.update(verified=True, archiveSHA256=capture['archiveSHA256'], archiveBytes=reader.count,
                       blockCount=len(expected), samples=capture['samples'], originalArchiveUnchanged=True)
    except Exception as error:
        receipt['errorType'] = type(error).__name__
        raise
    finally:
        (root / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    run(args.directory)
