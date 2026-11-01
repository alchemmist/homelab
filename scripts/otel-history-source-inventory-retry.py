"""Explicit retry of timed-out source inventory, using already SHA-verified data.

Failed attempt is preserved. No archive re-extraction, import, or publication.
Runtime/IO/RSS observations make a further timeout diagnosable.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BLOCKS = {'01M5P6GGQM3K9NAF43KP5JX3JW': 4606695568, '01M5VBA2WTA1H8QE21D6PHVHWY': 5955368159,
          '01M60G3GYDQYMVRYQ7NSNB2FGR': 6137437488, '01M612NE3X7QKRHX9Q1NWWPEH4': 260844250,
          '01M619H5BTN00D1MVWZNRTJ2VC': 261337432, '01M61BHKG8EYTCRNMDHRYTBNKR': 1043291602}
SHA = 'fc0f73919caa2615441e0053b632d6b48b087d5542bcc2c39c688267cea48632'


def save(root, name, value):
    temp = root / (name + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(root / name)


def run(corpus, output, binary, binary_sha):
    os.umask(0o077)
    old = json.loads((corpus / 'result.json').read_text())
    archive = json.loads((corpus / 'archive-receipt.json').read_text())
    if old.get('errorType') != 'TimeoutExpired' or archive.get('originalArchiveSHA256Verified') is not True or archive.get('archiveSHA256') != SHA or output.exists():
        raise ValueError('Explicit preserved timeout and already verified corpus required')
    with binary.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != binary_sha:
            raise ValueError('Canonical reader executable pin differs')
    output.mkdir(mode=0o700)
    report = {'success': False, 'previousTimeoutPreserved': True, 'originalArchiveSHA256Verified': True,
              'archiveSHA256': SHA, 'productionModified': False, 'canonicalInventories': {}}
    try:
        reserve_deadline = time.monotonic() + 3600
        while True:
            memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
            available = int(memory['MemAvailable'].split()[0]) * 1024
            if available >= 896 * 1024**2:
                break
            save(output, 'progress.json', {'phase': 'await-safe-host-reserve', 'availableBytes': available, 'requiredAvailableBytes': 896 * 1024**2})
            if time.monotonic() >= reserve_deadline:
                raise TimeoutError('Safe host reserve did not become available; no reader started')
            time.sleep(60)
        for block, expected in BLOCKS.items():
            source = corpus / 'source' / block
            metadata = json.loads((source / 'meta.json').read_text())
            if metadata['ulid'] != block or metadata['stats']['numSamples'] != expected or any(path.is_symlink() for path in source.rglob('*')):
                raise ValueError('Preserved original candidate identity differs')
            started = time.monotonic()
            with (output / (block + '.stderr')).open('x') as errors, (output / (block + '.json')).open('x') as result:
                process = subprocess.Popen([str(binary), 'inventory', '--source', str(source)], stdout=result, stderr=errors,
                                           env=dict(os.environ, GOMAXPROCS='1', GOMEMLIMIT='128MiB'))
                try:
                    while process.poll() is None:
                        elapsed = time.monotonic() - started
                        if elapsed > 14400:
                            raise TimeoutError('Original block inventory exceeded explicit 4h deadline')
                        observed = {'block': block, 'phase': 'canonical-source-inventory', 'elapsedSeconds': elapsed,
                                    'completedInventories': len(report['canonicalInventories'])}
                        try:
                            status = dict(line.split(':', 1) for line in Path('/proc/' + str(process.pid) + '/status').read_text().splitlines() if ':' in line)
                            observed['rssKiB'] = int(status['VmRSS'].split()[0])
                            observed['io'] = dict(line.split(':', 1) for line in Path('/proc/' + str(process.pid) + '/io').read_text().splitlines())
                        except (FileNotFoundError, ProcessLookupError, KeyError):
                            pass
                        save(output, 'progress.json', observed)
                        time.sleep(30)
                    if process.returncode:
                        raise subprocess.CalledProcessError(process.returncode, block)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=10)
            inventory = json.loads((output / (block + '.json')).read_text())
            if inventory['samples'] != expected:
                raise ValueError('Full source sample count differs')
            report['canonicalInventories'][block] = {'samples': expected, 'canonicalSHA256': inventory['canonicalSHA256'],
                                                   'externalLabels': metadata.get('thanos', {}).get('labels', {}),
                                                   'minTime': metadata['minTime'], 'maxTime': metadata['maxTime']}
            save(output, 'canonical-progress.json', report)
        report['success'] = True
    except Exception as error:
        report['errorType'] = type(error).__name__
        raise
    finally:
        save(output, 'result.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['corpus', 'output', 'binary']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    args = parser.parse_args()
    run(args.corpus, args.output, args.binary, args.binary_sha256)
