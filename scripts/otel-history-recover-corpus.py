"""Recover the six approved raw backup candidates and rebuild source hash receipts.

Finite, unprivileged, bounded; performs no import or production publication.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

BLOCKS = ('01M5P6GGQM3K9NAF43KP5JX3JW', '01M5VBA2WTA1H8QE21D6PHVHWY',
          '01M60G3GYDQYMVRYQ7NSNB2FGR', '01M612NE3X7QKRHX9Q1NWWPEH4',
          '01M619H5BTN00D1MVWZNRTJ2VC', '01M61BHKG8EYTCRNMDHRYTBNKR')
ARCHIVE_SHA = 'fc0f73919caa2615441e0053b632d6b48b087d5542bcc2c39c688267cea48632'


def run(archive, output, reader_path, binary, binary_sha):
    os.umask(0o077)
    if archive.is_symlink() or output.exists():
        raise ValueError('Regular original archive and new corpus output required')
    with binary.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != binary_sha:
            raise ValueError('Canonical inventory binary pin differs')
    disk = shutil.disk_usage(output.parent)
    if disk.free - 24 * 1024**3 < disk.total // 5:
        raise ValueError('Corpus recovery would breach 20% filesystem reserve')
    spec = importlib.util.spec_from_file_location('source_reader', reader_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    output.mkdir(mode=0o700)
    before = archive.stat()
    receipt = {'success': False, 'productionPublished': False, 'canonicalInventories': {}}
    try:
        seen = set()
        total = 0
        with archive.open('rb') as incoming:
            reader = helper.HashReader(incoming, output)
            with tarfile.open(fileobj=reader, mode='r|gz') as tar:
                for member in tar:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('Unsafe original archive member')
                    if not path.parts or path.parts[0] not in BLOCKS:
                        continue
                    if member.name in seen or not (member.isfile() or member.isdir()):
                        raise ValueError('Duplicate or nonregular corpus member')
                    seen.add(member.name)
                    target = output / 'source' / Path(*path.parts)
                    if member.isdir():
                        target.mkdir(mode=0o700, parents=True, exist_ok=True)
                        continue
                    total += member.size
                    if total > 24 * 1024**3:
                        raise ValueError('Corpus exceeds bounded extraction budget')
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with tar.extractfile(member) as source, target.open('xb') as destination:
                        shutil.copyfileobj(source, destination, 1024**2)
                    if target.stat().st_size != member.size:
                        raise ValueError('Truncated original corpus member')
            while reader.read(4 * 1024**2):
                pass
        after = archive.stat()
        if reader.digest.hexdigest() != ARCHIVE_SHA or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Original archive differs or changed during extraction')
        receipt.update(originalArchiveSHA256Verified=True, archiveSHA256=ARCHIVE_SHA, sourceBytes=total)
        helper.atomic(output / 'archive-receipt.json', receipt)
        for block in BLOCKS:
            source = output / 'source' / block
            metadata = json.loads((source / 'meta.json').read_text())
            if metadata['ulid'] != block or (source / 'deletion-mark.json').exists() or metadata.get('thanos', {}).get('downsample', {}).get('resolution', 0) != 0:
                raise ValueError('Unexpected original candidate semantics')
            helper.atomic(output / 'progress.json', {'phase': 'canonical-source-inventory', 'block': block, 'verifiedInventories': len(receipt['canonicalInventories'])})
            with (output / (block + '.stderr')).open('x') as errors, (output / (block + '.json')).open('x') as result:
                subprocess.run([str(binary), 'inventory', '--source', str(source)], stdout=result, stderr=errors, check=True, timeout=3600,
                               env=dict(os.environ, GOMAXPROCS='1', GOMEMLIMIT='128MiB'))
            inventory = json.loads((output / (block + '.json')).read_text())
            receipt['canonicalInventories'][block] = {'samples': inventory['samples'], 'canonicalSHA256': inventory['canonicalSHA256']}
            helper.atomic(output / 'canonical-progress.json', receipt)
        receipt['success'] = True
    except Exception as error:
        receipt['errorType'] = type(error).__name__
        raise
    finally:
        helper.atomic(output / 'result.json', receipt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['archive', 'output', 'reader', 'binary']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    args = parser.parse_args()
    run(args.archive, args.output, args.reader, args.binary, args.binary_sha256)
