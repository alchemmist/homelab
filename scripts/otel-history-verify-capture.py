"""Verify an immutable live repaired capture on a healthy host, without importing.

Only the exact previously approved repaired data are accepted. No additional
sample loss, source mutation or production publication is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

EXPECTED = '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209'
ULID = '01M66BZJJH7AX3HTZFRZD02SXP'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(root, binary, binary_sha):
    os.umask(0o077)
    if (root / 'result.json').exists():
        raise ValueError('Existing capture verification must be inspected, not overwritten')
    receipt = {'success': False, 'productionModified': False, 'additionalSamplesRemoved': 0}
    try:
        source = json.loads((root / 'capture.json').read_text())
        if source['sourceULID'] != ULID or source['expectedSamples'] != 6383043932 or source['expectedCanonicalSHA256'] != EXPECTED or source['originalFilesUnchanged'] is not True:
            raise ValueError('Unexpected repaired source identity')
        archive = root / 'candidate.tar'
        if archive.stat().st_size != source['archiveBytes'] or digest(archive) != source['archiveSHA256'] or digest(binary) != binary_sha:
            raise ValueError('Capture transfer or executable checksum differs')
        disk = shutil.disk_usage(root)
        if disk.free - archive.stat().st_size * 2 < disk.total // 5:
            raise ValueError('Capture extraction would breach 20% reserve')
        output = root / 'source'
        output.mkdir(mode=0o700)
        with tarfile.open(archive) as tar:
            total = 0
            seen = set()
            for member in tar.getmembers():
                path = Path(member.name)
                total += member.size
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != ULID or not (member.isfile() or member.isdir()) or member.name in seen or total > archive.stat().st_size * 2:
                    raise ValueError('Unsafe immutable capture member')
                seen.add(member.name)
            tar.extractall(output, filter='data')
        with (root / 'inventory.stderr').open('x') as errors, (root / 'inventory.json').open('x') as result:
            subprocess.run([str(binary), 'inventory', '--source', str(output / ULID)], stdout=result, stderr=errors,
                           check=True, timeout=14400, env=dict(os.environ, GOMAXPROCS='1', GOMEMLIMIT='256MiB'))
        inventory = json.loads((root / 'inventory.json').read_text())
        if inventory['samples'] != 6383043932 or inventory['canonicalSHA256'] != EXPECTED:
            raise ValueError('Live source differs from independently verified approved repair')
        receipt.update(success=True, samples=inventory['samples'], canonicalSHA256=EXPECTED,
                       healthyHostFullCanonicalInventoryVerified=True, archiveTransferSHA256Verified=True,
                       sourceDirectory=str(output / ULID), otlpRoundtripStillRequired=True)
    except Exception as error:
        receipt['errorType'] = type(error).__name__
        raise
    finally:
        (root / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    args = parser.parse_args()
    run(args.root, args.binary, args.binary_sha256)
