"""Normalize completed old-worker outputs in isolated copies, never served blocks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def check_receipt(receipt, item):
    expected = item['verification']
    if (receipt.get('verified') is not True or receipt.get('nativePhysicalMetadataVerified') is not True
            or receipt.get('canonicalSHA256') != expected['canonicalSHA256']
            or receipt.get('samples') != expected['samples']
            or receipt.get('productionModified') is not False
            or receipt.get('originalOutputModified') is not False):
        raise ValueError('Native metadata receipt does not match unchanged canonical source')


def run(args):
    os.umask(0o077)
    args.workspace.mkdir(mode=0o700, exist_ok=False)
    with args.binary.open('rb') as stream:
        binary_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    initial = json.loads(args.initial.read_text())
    if initial.get('success') is not True:
        raise ValueError('Initial isolated normalization was not successful')
    known = {item['block']: item for item in initial['completed']}
    completed = {}
    report = {'startedAt': datetime.now(timezone.utc).isoformat(), 'binarySHA256': binary_hash,
              'success': False, 'productionModified': False, 'coordinatorOutputsModified': False,
              'historyMigrationComplete': False, 'completed': completed}
    try:
        while True:
            state = json.loads(args.state.read_text())
            if args.job_result.exists() and not json.loads(args.job_result.read_text()).get('success'):
                raise RuntimeError('Original history coordinator failed; do not launch further normalization')
            for key, item in state['blocks'].items():
                if item.get('status') != 'roundtrip-verified' or key in completed:
                    continue
                block_id = Path(item['restoredBlock']).name
                if block_id in known:
                    receipt = known[block_id]
                else:
                    with args.binary.open('rb') as stream:
                        if hashlib.file_digest(stream, 'sha256').hexdigest() != binary_hash:
                            raise ValueError('Pinned normalizer executable changed')
                    output = args.workspace / (item['ulid'] + '-normalized')
                    print('Normalize completed block', item['ulid'], flush=True)
                    subprocess.run([str(args.binary), 'normalize-native-metadata', '--source', item['export'],
                                    '--block', item['restoredBlock'], '--output', str(output)],
                                   env={**os.environ, 'GOMAXPROCS': '2', 'GOMEMLIMIT': '2GiB'}, check=True, timeout=21600)
                    receipt = json.loads((output / 'verification.json').read_text())
                check_receipt(receipt, item)
                completed[key] = receipt
                write(args.workspace / 'progress.json', report)
            if state.get('complete') is True:
                expected = {key for key, item in state['blocks'].items() if item.get('status') == 'roundtrip-verified'}
                if set(completed) != expected:
                    raise ValueError('Not all completed source blocks were normalized')
                report['success'] = True
                break
            time.sleep(60)
    except Exception as error:
        report['errorType'] = type(error).__name__
        raise
    finally:
        report['finishedAt'] = datetime.now(timezone.utc).isoformat()
        write(args.workspace / 'result.json', report)


def main():
    parser = argparse.ArgumentParser()
    for name in ('state', 'job-result', 'binary', 'workspace', 'initial'):
        parser.add_argument('--' + name, required=True, type=Path)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
