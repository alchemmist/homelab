import argparse
import hashlib
import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile


BLOCK_ID = re.compile(r'^[0-9A-HJKMNP-TV-Z]{26}$')
MANIFEST_NAME = 'otel-backup-manifest.json'


class HashReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        self.size += len(data)
        return data


def block_inventory(root):
    blocks = []
    for directory in sorted(root.iterdir()):
        if not BLOCK_ID.fullmatch(directory.name):
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Invalid block directory')
        meta_path = directory / 'meta.json'
        if not meta_path.is_file():
            raise ValueError(f'Incomplete block: {directory.name}')
        if meta_path.is_symlink():
            raise ValueError('Symlink in block metadata')
        meta = json.loads(meta_path.read_text())
        if meta.get('ulid') != directory.name or meta['maxTime'] <= meta['minTime']:
            raise ValueError('Invalid block metadata')
        blocks.append({
            'ulid': meta['ulid'], 'minTime': meta['minTime'], 'maxTime': meta['maxTime'],
            'resolution': meta.get('thanos', {}).get('downsample', {}).get('resolution', 0),
            'deletionMarked': (directory / 'deletion-mark.json').exists(),
        })
    return blocks


def pack(root, output):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Archive source must be a real directory')
    blocks = block_inventory(root)
    files = {}
    with tarfile.open(fileobj=output, mode='w|') as archive:
        for block in blocks:
            directory = root / block['ulid']
            for path in sorted(directory.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Symlinks are forbidden in backup blocks')
                if path.is_dir():
                    continue
                name = path.relative_to(root).as_posix()
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    info = archive.gettarinfo(str(path), arcname=name)
                    if not info.isfile():
                        raise ValueError('Only regular block files can be archived')
                    reader = HashReader(stream)
                    archive.addfile(info, reader)
                    after = os.fstat(stream.fileno())
                    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                        raise ValueError('Source changed while backing up')
                    if reader.size != before.st_size:
                        raise ValueError('Incomplete source read')
                    files[name] = {'size': reader.size, 'sha256': reader.digest.hexdigest()}
        manifest = {'schemaVersion': 1, 'blocks': blocks, 'files': files}
        data = json.dumps(manifest, sort_keys=True, allow_nan=False).encode()
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(data)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(data))
    return manifest


def verify(source):
    files = {}
    manifest = None
    metadata = {}
    with tarfile.open(fileobj=source, mode='r|') as archive:
        for member in archive:
            name = member.name
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or str(path) != name or not member.isfile():
                raise ValueError('Unsafe archive member')
            if manifest is not None:
                raise ValueError('Manifest must be the final archive member')
            handle = archive.extractfile(member)
            if name == MANIFEST_NAME:
                if member.size > 64 * 1024 ** 2:
                    raise ValueError('Oversized manifest')
                manifest = json.load(handle)
                continue
            if name in files or not path.parts or not BLOCK_ID.fullmatch(path.parts[0]):
                raise ValueError('Duplicate or invalid archive member')
            reader = HashReader(handle)
            meta_data = bytearray()
            is_meta = len(path.parts) == 2 and path.name == 'meta.json'
            while True:
                data = reader.read(1024 * 1024)
                if not data:
                    break
                if is_meta:
                    meta_data.extend(data)
                    if len(meta_data) > 16 * 1024 ** 2:
                        raise ValueError('Oversized block metadata')
            if reader.size != member.size:
                raise ValueError('Truncated archive file')
            files[name] = {'size': reader.size, 'sha256': reader.digest.hexdigest()}
            if is_meta:
                meta = json.loads(meta_data)
                if meta.get('ulid') != path.parts[0] or meta['maxTime'] <= meta['minTime']:
                    raise ValueError('Invalid archived block metadata')
                metadata[meta['ulid']] = meta
    if manifest is None or manifest.get('schemaVersion') != 1 or manifest.get('files') != files:
        raise ValueError('Missing or mismatched archive manifest')
    declared = {block['ulid']: block for block in manifest['blocks']}
    if len(declared) != len(manifest['blocks']) or set(declared) != set(metadata):
        raise ValueError('Block inventory mismatch')
    for ulid, meta in metadata.items():
        block = declared[ulid]
        resolution = meta.get('thanos', {}).get('downsample', {}).get('resolution', 0)
        if (block['minTime'], block['maxTime'], block['resolution']) != (meta['minTime'], meta['maxTime'], resolution):
            raise ValueError('Block metadata mismatch')
        if block['deletionMarked'] != (ulid + '/deletion-mark.json' in files):
            raise ValueError('Deletion marker mismatch')
    if {PurePosixPath(name).parts[0] for name in files} != set(declared):
        raise ValueError('Uninventoried block files')
    return {'schemaVersion': 1, 'verified': True, 'blockCount': len(metadata),
            'fileCount': len(files), 'bytes': sum(item['size'] for item in files.values()),
            'blocks': manifest['blocks']}


def verify_file(path, expected_sha256=None):
    if expected_sha256 is not None:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while data := stream.read(4 * 1024 ** 2):
                digest.update(data)
        if digest.hexdigest() != expected_sha256:
            raise ValueError('Archive SHA-256 differs from the verified source')
    opener = gzip.open if path.name.endswith('.gz') else open
    with opener(path, 'rb') as source:
        return verify(source)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('pack')
    create.add_argument('--root', type=Path, required=True)
    check = sub.add_parser('verify')
    check.add_argument('--archive', type=Path, required=True)
    check.add_argument('--expected-sha256')
    args = parser.parse_args()
    try:
        if args.command == 'pack':
            pack(args.root, sys.stdout.buffer)
        else:
            print(json.dumps(verify_file(args.archive, args.expected_sha256)))
        return 0
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
