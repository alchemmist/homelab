"""Bind independently queried historical external labels to a separate snapshot copy.

Never edits coordinator outputs, original metadata, ordinary sample labels or
production buckets. Original strict metadata verification remains unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def bind(source, output, proof_path, expected_path, binary):
    os.umask(0o077)
    with binary.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != 'e7db18da5afcde9dcadfede588bf2f3b27aaf23f5beba03f916cfac50f5454d2':
            raise ValueError('Unpinned canonical inventory executable')
    source = source.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Separate new context-bound output required')
    proof = json.loads(proof_path.read_text())
    expected = json.loads(expected_path.read_text())
    metadata = json.loads((source / 'meta.json').read_text())
    if metadata.get('thanos') is not None or proof.get('verifiedHistoricalQueryContextForAnchors') is not True:
        raise ValueError('Only an unbound snapshot and independent historical proof are accepted')
    if metadata['ulid'] != proof['restoredSnapshot']:
        raise ValueError('Historical query proof does not identify this restored snapshot')
    if len(proof.get('checks', [])) != 3 or any(check.get('originalHistoricalRawLabelsAndFloatBitsMatch') is not True or check.get('sourceSampleTimestampMatches') is not True for check in proof['checks']):
        raise ValueError('Historical ordinary labels, float bits and source times must all match')
    labels = proof['externalLabels']
    if set(labels) != {'prometheus', 'prometheus_replica'} or any(not isinstance(value, str) or not value for value in labels.values()):
        raise ValueError('Unexpected external label context')
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlinked snapshot members forbidden')
    size = sum(path.stat().st_size for path in source.rglob('*') if path.is_file())
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    disk = shutil.disk_usage(output.parent)
    if disk.free - size < disk.total // 5:
        raise ValueError('Snapshot binding would violate 20% disk reserve')
    original_hash = hashlib.sha256((source / 'meta.json').read_bytes()).hexdigest()
    block = output / metadata['ulid']
    shutil.copytree(source, block)
    segments = sorted(path.name for path in (block / 'chunks').iterdir())
    files = [{'rel_path': 'chunks/' + name, 'size_bytes': (block / 'chunks' / name).stat().st_size} for name in segments]
    files += [{'rel_path': 'index', 'size_bytes': (block / 'index').stat().st_size}, {'rel_path': 'meta.json'}]
    metadata['thanos'] = {'labels': labels, 'downsample': {'resolution': 0}, 'files': files, 'segment_files': segments}
    (block / 'meta.json').write_text(json.dumps(metadata, separators=(',', ':')))
    # Inventory recomputes every ordinary-label/timestamp/float-bit sample hash.
    completed = subprocess.run([str(binary), 'inventory', '--source', str(block)], capture_output=True, text=True, check=True, timeout=600)
    inventory = json.loads(completed.stdout)
    if inventory['samples'] != expected['samples'] or inventory['canonicalSHA256'] != expected['canonicalSHA256']:
        raise ValueError('Context binding changed canonical source data')
    if hashlib.sha256((source / 'meta.json').read_bytes()).hexdigest() != original_hash:
        raise ValueError('Original coordinator metadata changed')
    receipt = {'contextBoundInIsolatedCopy': True, 'sourceMetadataUnchanged': True, 'productionModified': False,
               'samples': inventory['samples'], 'canonicalSHA256': inventory['canonicalSHA256'],
               'historicalContextProofSHA256': hashlib.sha256(proof_path.read_bytes()).hexdigest(),
               'block': metadata['ulid'], 'nativeQueryValidationStillRequired': True}
    (output / 'context-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['source', 'output', 'proof', 'expected', 'binary']:
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    bind(args.source, args.output, args.proof, args.expected, args.binary)
