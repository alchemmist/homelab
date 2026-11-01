"""Finite, unprivileged, single-block offline recovery importer.

Run only inside an explicitly memory/CPU/runtime-limited user systemd unit.
Never publishes data or modifies original backups/production TSDBs.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def save(path, document):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(document, indent=2) + '\n')
    temporary.replace(path)


def run(root, expected_binary, expected_samples):
    os.umask(0o077)
    control = [line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')]
    if len(control) != 1:
        raise ValueError('A bounded cgroup v2 user service is required')
    group = Path('/sys/fs/cgroup') / control[0].lstrip('/')
    maximum = (group / 'memory.max').read_text().strip()
    quota, period = (group / 'cpu.max').read_text().split()
    if maximum == 'max' or int(maximum) > 3 * 1024**3 or (group / 'memory.swap.max').read_text().strip() != '0' or quota == 'max' or int(quota) > int(period) * 1.5:
        raise ValueError('Recovery requires hard memory/swap/CPU limits')
    proof = json.loads((root / 'source-archive-proof.json').read_text())
    if proof.get('verified') is not True or proof.get('archiveSHA256') != 'fc0f73919caa2615441e0053b632d6b48b087d5542bcc2c39c688267cea48632':
        raise ValueError('Verified original archive provenance required')
    with (root / 'import.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / 'result.json').exists():
            raise ValueError('Prior import result retained; do not overwrite it')
        binary = root / 'otel-history'
        with binary.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected_binary:
                raise ValueError('Recovery executable checksum mismatch')
        sources = list((root / 'source').glob('*/meta.json'))
        if len(sources) != 1:
            raise ValueError('Exactly one recovered source block required')
        source = sources[0].parent
        if source.name != proof['block']:
            raise ValueError('Recovered source and verified archive block differ')
        if any(path.is_symlink() for path in source.rglob('*')):
            raise ValueError('Symlinked recovery source forbidden')
        disk = shutil.disk_usage(root)
        if disk.free - 32 * 1024**3 < disk.total // 5:
            raise ValueError('Insufficient bounded workspace with 20% reserve')
        status = {'success': False, 'productionPublished': False, 'sourceBlock': source.name,
                  'startedAtUnix': time.time(), 'binarySHA256': expected_binary}
        try:
            def execute(phase, arguments):
                save(root / 'progress.json', dict(status, phase=phase))
                with (root / (phase + '.stderr')).open('x') as errors, (root / (phase + '.stdout')).open('x') as output:
                    subprocess.run([str(binary), *arguments], stdout=output, stderr=errors, check=True,
                                   env=dict(os.environ, GOMAXPROCS='2', GOMEMLIMIT='2GiB'))
                return (root / (phase + '.stdout')).read_text()
            inventory = json.loads(execute('source-inventory', ['inventory', '--source', str(source)]))
            if inventory['samples'] != expected_samples:
                raise ValueError('Recovered source sample count differs from approved candidate')
            save(root / 'source-inventory.json', inventory)
            exported = root / 'otlp'
            execute('export', ['export', '--source', str(source), '--output', str(exported), '--max-bytes', str(24 * 1024**3)])
            restored = root / 'restored'
            execute('import', ['import', '--source', str(exported), '--output', str(restored)])
            blocks = list(restored.glob('*/meta.json'))
            if len(blocks) != 1:
                raise ValueError('Exactly one restored native block required')
            block = blocks[0].parent
            execute('verify', ['verify', '--source', str(exported), '--block', str(block)])
            status.update(success=True, samples=inventory['samples'], canonicalSHA256=inventory['canonicalSHA256'],
                          restoredBlock=str(block), sourceDirectory=str(source), exportDirectory=str(exported),
                          nativeThanosVerificationStillRequired=True)
        except Exception as error:
            status['errorType'] = type(error).__name__
            raise
        finally:
            status['finishedAtUnix'] = time.time()
            save(root / 'result.json', status)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--expected-samples', required=True, type=int)
    args = parser.parse_args()
    run(args.root, args.binary_sha256, args.expected_samples)
