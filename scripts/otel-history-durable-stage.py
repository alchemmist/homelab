"""Relocate completed private native-validation buckets to durable local staging.

No production publication, cross-filesystem fallback, data rewriting or deletion.
"""
import json
import os
from pathlib import Path
import re
import shutil

BASE = Path('/var/lib/homelab-otel-history/staged')


def regular_inventory(root):
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink in verified native bucket')
        if path.is_file():
            stat = path.stat()
            result[str(path.relative_to(root))] = [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
    return result


def run():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ValueError('Root-owned native staging required')
    BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if BASE.is_symlink() or BASE.stat().st_uid != 0:
        raise ValueError('Untrusted durable stage')
    receipts = []
    for root in sorted(Path('/var/tmp').glob('otel-history-native-compat-*')):
        result_path = root / 'result.json'
        if root.is_symlink() or not result_path.exists():
            continue
        if root.stat().st_uid != 0 or root.stat().st_mode & 0o077:
            raise ValueError('Untrusted native validation root')
        checked = json.loads(result_path.read_text())
        if checked.get('verified') is not True or not re.fullmatch(r'[0-9A-HJKMNP-TV-Z]{26}', checked['block']):
            raise ValueError('Native compatibility result did not pass')
        bucket = root / 'bucket'
        if not bucket.exists():
            continue
        active = False
        for process in Path('/proc').glob('[0-9]*/cmdline'):
            try:
                if (str(root / 'thanos').encode() + b'\x00') in process.read_bytes():
                    active = True
                    break
            except (FileNotFoundError, ProcessLookupError):
                continue
        if active:
            continue
        expected = regular_inventory(bucket)
        if not (bucket / checked['block'] / 'meta.json').is_file():
            raise ValueError('Verified block is absent from its bucket')
        target = BASE / checked['block']
        if target.exists():
            raise ValueError('Durable block destination already exists; inspect rather than overwrite')
        target.mkdir(mode=0o700)
        if bucket.stat().st_dev != target.stat().st_dev:
            raise ValueError('Durable relocation requires same-filesystem atomic rename')
        os.rename(bucket, target / 'bucket')
        if regular_inventory(target / 'bucket') != expected:
            raise ValueError('Native inode/size/mtime inventory changed during atomic relocation')
        for name in ['request.json', 'result.json']:
            shutil.copyfile(root / name, target / name)
            (target / name).chmod(0o600)
        receipt = {'block': checked['block'], 'durableDirectory': str(target), 'sameFilesystemRenameVerified': True,
                   'fileCount': len(expected), 'fileBytes': sum(entry[2] for entry in expected.values()),
                   'productionPublished': False, 'originalHistoryDeleted': False}
        (target / 'durability.json').write_text(json.dumps(receipt, indent=2) + '\n')
        (root / 'relocation.json').write_text(json.dumps(receipt, indent=2) + '\n')
        receipts.append(receipt)
    print(json.dumps({'durablyStaged': receipts, 'productionPublished': False}))


if __name__ == '__main__':
    run()
