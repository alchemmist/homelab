"""Finite full-sample subset proofs for compacted backup ranges; no publication."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path('/var/lib/homelab-otel-history/coverage-20261031')
PRODUCER = Path('/home/alchemmist/.local/share/homelab/otel-current-source-20261031')
TARGET_ID = '01M66BZJJH7AX3HTZFRZD02SXP'
TARGET_HASH = '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209'
COUNTS = (235173517, 260844250, 261337432, 1043291602)


def save(name, document):
    temp = BASE / (name + '.tmp')
    temp.write_text(json.dumps(document, indent=2) + '\n')
    temp.replace(BASE / name)


def inventory(root):
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink in preserved native source')
        if path.is_file():
            stat = path.stat()
            result[str(path.relative_to(root))] = [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
    return result


def run():
    os.umask(0o077)
    if os.geteuid() != 0 or (BASE / 'result.json').exists():
        raise ValueError('Protected new full-coverage job required')
    report = {'success': False, 'productionModified': False, 'targetOtlpRoundtripStillRequired': True, 'subsets': []}
    deadline = time.monotonic() + 21600
    try:
        with (BASE / 'subset-check').open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != (BASE / 'subset-check.sha256').read_text().strip():
            raise ValueError('Subset verifier binary pin differs')
        save('progress.json', dict(report, phase='await-healthy-target-canonical-inventory'))
        while not (PRODUCER / 'result.json').exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('Healthy-target canonical verification deadline exceeded')
            time.sleep(30)
        target_receipt = json.loads((PRODUCER / 'result.json').read_text())
        if target_receipt.get('success') is not True or target_receipt.get('canonicalSHA256') != TARGET_HASH or target_receipt.get('samples') != 6383043932:
            raise ValueError('Full healthy-host target integrity was not established')
        save('target-integrity.json', target_receipt)
        target = PRODUCER / 'source' / TARGET_ID
        protected = BASE / 'preserved-target'
        protected.mkdir(mode=0o700)
        if target.stat().st_dev != protected.stat().st_dev:
            raise ValueError('Target preservation requires same-filesystem rename')
        before = inventory(target)
        destination = protected / TARGET_ID
        os.rename(target, destination)
        if inventory(destination) != before:
            raise ValueError('Canonical target inode inventory changed during preservation')
        destination.chmod(0o700)
        os.chown(destination, 0, 0)
        save('target-preservation.json', {'canonicalSHA256': TARGET_HASH, 'samples': 6383043932, 'sameFilesystemRenameVerified': True,
                                         'protectedDirectory': str(destination), 'productionModified': False})
        # Each completed candidate is private, native-validated and immutable.
        for expected in COUNTS:
            while True:
                candidates = []
                for metadata in Path('/var/lib/homelab-otel-history/staged').glob('*/bucket/*/meta.json'):
                    meta = json.loads(metadata.read_text())
                    if meta['stats']['numSamples'] == expected:
                        checked = json.loads((metadata.parents[2] / 'result.json').read_text())
                        if checked.get('verified') is True:
                            candidates.append(metadata.parent)
                if len(candidates) > 1:
                    raise ValueError('Ambiguous full-source coverage candidate')
                if candidates:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Native-verified source candidate did not become ready')
                time.sleep(30)
            candidate = candidates[0]
            save('progress.json', dict(report, phase='full-source-subset-check', source=candidate.name))
            with (BASE / (candidate.name + '.stderr')).open('x') as errors:
                done = subprocess.run([str(BASE / 'subset-check'), '--source', str(candidate), '--target', str(destination)],
                                      stdout=subprocess.PIPE, stderr=errors, text=True, check=True,
                                      timeout=max(1, deadline - time.monotonic()), env=dict(os.environ, GOMAXPROCS='1', GOMEMLIMIT='256MiB'))
            proof = json.loads(done.stdout)
            if proof.get('fullSourceSubsetVerified') is not True or proof.get('sourceSamplesVerified') != expected:
                raise ValueError('Complete source subset was not verified')
            proof.update(source=candidate.name, target=TARGET_ID, targetCanonicalSHA256=TARGET_HASH)
            save(candidate.name + '.json', proof)
            report['subsets'].append(proof)
        report.update(success=True, sourceSamplesVerified=sum(COUNTS), targetRawCanonicalInventoryVerifiedSeparately=True)
    except Exception as error:
        report['errorType'] = type(error).__name__
        raise
    finally:
        save('result.json', report)


if __name__ == '__main__':
    run()
