"""Finite original-to-restored full canonical comparison on the healthy fast host.

Exactly one temporary original copy at a time; original archive and extracted
corpus stay on socrat-3. This is a read-only verifier, never a second importer.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import tarfile

REMOTE = Path('/home/alchemmist/.local/share/homelab/otel-golden-sources-20261101')
CORPUS = '/home/alchemmist/.local/share/homelab/otel-history-recovery-20261031/source-corpus'
BINARY = Path('/home/alchemmist/.local/share/homelab/otel-history-recovery-20261031/otel-history')
PIN = '9725e698476cbd4ab38f04c3481083067574fd580c479afdc57bfd4c3f8bab63'


def save(root, name, value):
    temporary = root / (name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(root / name)


def references():
    return json.loads((REMOTE / 'references.json').read_text())


def receive(block):
    import sys
    if block not in references()['references'] or (REMOTE / 'inputs' / block).exists():
        raise ValueError('New known source copy required')
    total = 0
    seen = set()
    with tarfile.open(fileobj=sys.stdin.buffer, mode='r|gz') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            canonical = str(path)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != block or canonical in seen or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe original-copy archive')
            seen.add(canonical)
            total += member.size
            if total > 7 * 1024**3:
                raise ValueError('Original-copy transfer exceeds bounded budget')
            archive.extract(member, path=REMOTE / 'inputs', filter='data')


def read(block):
    expected = references()['references'][block]
    source = REMOTE / 'inputs' / block
    result = {'success': False, 'originalBlock': block, 'productionModified': False,
              'originalArchiveAndCorpusDeleted': False, 'algorithm': 'legacy-full-canonical-v1'}
    try:
        meta = json.loads((source / 'meta.json').read_text())
        if source.is_symlink() or any(path.is_symlink() for path in source.rglob('*')):
            raise ValueError('Symlinked original copy rejected')
        if meta['ulid'] != block or meta['stats']['numSamples'] != expected['samples'] or any(meta[key] != expected[key] for key in ['minTime', 'maxTime']) or meta.get('thanos', {}).get('labels', {}) != expected['externalLabels']:
            raise ValueError('Original source context differs from restored reference')
        with BINARY.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != PIN:
                raise ValueError('Full canonical reader executable pin differs')
        process = subprocess.run([str(BINARY), 'inventory', '--source', str(source)], capture_output=True, text=True,
                                 timeout=14400, env=dict(os.environ, GOMAXPROCS='1', GOMEMLIMIT='256MiB'))
        (REMOTE / 'receipts' / (block + '.stderr')).write_text(process.stderr)
        process.check_returncode()
        actual = json.loads(process.stdout)
        if actual['samples'] != expected['samples'] or actual['canonicalSHA256'] != expected['canonicalSHA256']:
            raise ValueError('Full original labels/timestamps/float-bits/multiplicity hash differs')
        result.update(success=True, samples=actual['samples'], canonicalSHA256=actual['canonicalSHA256'],
                      fullOriginalToRestoredCanonicalEqualityVerified=True,
                      sourceArchiveSHA256=references()['sourceArchiveSHA256'])
        # Only this verified transport copy is removed. Both originals remain on socrat-3.
        shutil.rmtree(source)
        result['verifiedTemporaryCopyRemoved'] = True
    except Exception as error:
        result['errorType'] = type(error).__name__
        raise
    finally:
        save(REMOTE / 'receipts', block + '.json', result)
    print(json.dumps(result))


def controller(root):
    config = str(Path.home() / '.ssh/homelab-otel-migration.conf')
    refs = json.loads((root / 'golden-source-references.json').read_text())
    output = root / 'golden-comparison-20261101'
    output.mkdir(mode=0o700)
    report = {'success': False, 'productionModified': False, 'blocks': {},
              'sourceArchiveSHA256': refs['sourceArchiveSHA256']}

    def ssh(host, arguments, **kwargs):
        return subprocess.run(['ssh', '-F', config, host, shlex.join(arguments)], check=True, **kwargs)

    def unit(name, memory, *command):
        return ['systemd-run', '--user', '--quiet', '--pipe', '--wait', '--collect', '--unit=' + name,
                '--property=MemoryMax=' + str(memory), '--property=MemorySwapMax=0', '--property=CPUQuota=100%',
                '--property=IOSchedulingClass=idle', '--property=OOMScoreAdjust=1000', '--property=RuntimeMaxSec=15000', *command]

    try:
        with (root / 'golden-controller.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            archive = json.loads(ssh('socrat-3', ['cat', CORPUS + '/archive-receipt.json'], capture_output=True, text=True, timeout=30).stdout)
            if archive.get('originalArchiveSHA256Verified') is not True or archive['archiveSHA256'] != refs['sourceArchiveSHA256']:
                raise ValueError('Already verified original corpus required')
            for index, block in enumerate(refs['references']):
                save(output, 'progress.json', {'block': block, 'phase': 'copy', 'completedBlocks': len(report['blocks'])})
                size = int(ssh('socrat-3', ['du', '-sb', CORPUS + '/source/' + block], capture_output=True, text=True, timeout=30).stdout.split()[0])
                guard = "import os; s=os.statvfs(%r); assert s.f_bavail*s.f_frsize-%d-16*1024**3 >= s.f_blocks*s.f_frsize//5, 'Insufficient disk headroom for ongoing importer and one source copy'" % (str(REMOTE), size)
                ssh('socrat-1', ['python3', '-c', guard], timeout=30)
                sender = unit('otel-golden-send-20261101-' + str(index), 128 * 1024**2, 'tar', '-czf', '-', '-C', CORPUS + '/source', block)
                receiver = unit('otel-golden-receive-20261101-' + str(index), 128 * 1024**2, 'python3', str(REMOTE / 'compare.py'), 'receive', '--block', block)
                with (output / (block + '.send.stderr')).open('w') as send_error, (output / (block + '.receive.stderr')).open('w') as receive_error:
                    producer = subprocess.Popen(['ssh', '-F', config, 'socrat-3', shlex.join(sender)], stdout=subprocess.PIPE, stderr=send_error)
                    consumer = subprocess.Popen(['ssh', '-F', config, 'socrat-1', shlex.join(receiver)], stdin=producer.stdout, stderr=receive_error)
                    producer.stdout.close()
                    try:
                        consumer.wait(timeout=7200)
                        producer.wait(timeout=30)
                        if consumer.returncode or producer.returncode:
                            raise ValueError('Source-copy transport failed; failed copy retained')
                    finally:
                        for process in [producer, consumer]:
                            if process.poll() is None:
                                process.terminate()
                                process.wait(timeout=30)
                save(output, 'progress.json', {'block': block, 'phase': 'full-canonical-comparison', 'completedBlocks': len(report['blocks'])})
                reader = unit('otel-golden-read-20261101-' + str(index), 512 * 1024**2, 'python3', str(REMOTE / 'compare.py'), 'read', '--block', block)
                actual = json.loads(ssh('socrat-1', reader, capture_output=True, text=True, timeout=15030).stdout)
                if actual.get('success') is not True:
                    raise ValueError('Full source comparison not successful')
                report['blocks'][block] = actual
                save(output, 'canonical-progress.json', report)
            report['success'] = True
    except Exception as error:
        report['errorType'] = type(error).__name__
        raise
    finally:
        save(output, 'result.json', report)


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['receive', 'read', 'controller'])
    parser.add_argument('--block')
    parser.add_argument('--controller-root', type=Path)
    args = parser.parse_args()
    if args.action == 'controller':
        controller(args.controller_root)
    elif args.action == 'receive':
        receive(args.block)
    else:
        read(args.block)
