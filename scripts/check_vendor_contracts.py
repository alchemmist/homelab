#!/usr/bin/env python3
"""Offline completeness/drift check of reviewed vendored trees; never downloads or rewrites.
A reviewed Git baseline is NOT independent upstream provenance or a security audit.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def inventory(root, directory):
    base = root/directory
    if base.is_symlink() or not base.is_dir() or not base.resolve().is_relative_to(root.resolve()):
        raise ValueError('Invalid vendor directory: '+directory)
    result = {}
    for path in sorted(base.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink in vendor tree: '+str(path.relative_to(root)))
        if path.is_file():
            result[path.relative_to(base).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def check(root=ROOT):
    contract = json.loads((root/'deploy/contracts/vendors.json').read_text())
    if contract['schemaVersion'] != 1:
        raise ValueError('Unsupported vendor contract schema')
    seen = set()
    for tree in contract['trees']:
        directory = tree['path']
        if directory in seen:
            raise ValueError('Duplicate vendor tree: '+directory)
        seen.add(directory)
        if tree['basis'] != 'reviewed-git-baseline' or not tree['reviewedCommit'] or not tree['provenanceNote']:
            raise ValueError('Missing explicit vendor baseline/provenance boundary')
        actual, expected = inventory(root, directory), tree['files']
        if not expected:
            raise ValueError('Empty vendor inventory: '+directory)
        added, removed = set(actual)-set(expected), set(expected)-set(actual)
        changed = {p for p in actual.keys() & expected.keys() if actual[p] != expected[p]}
        if added or removed or changed:
            raise ValueError(f'Vendor drift {directory}: added={sorted(added)}, removed={sorted(removed)}, changed={sorted(changed)}')
    return len(seen)

if __name__ == '__main__':
    print(f'Vendor contracts OK: {check()} reviewed trees; no upstream trust claim')
