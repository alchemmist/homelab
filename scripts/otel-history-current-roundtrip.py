"""Finite bounded OTLP roundtrip of the independently verified live repair.

No other importer may run. Never publishes or deletes originals. Source count,
full canonical digest, current source proof and 20% disk floor are mandatory.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

BASE = Path('/var/lib/homelab-otel-history/current-roundtrip-20261031-v2')
# The pinned exporter intentionally refuses all /var/lib, /srv, /etc and /host
# output. Keep that safety gate intact; only intermediate output uses this root-only workspace.
WORK = Path('/home/alchemmist/otel-history-current-roundtrip-work-20261031')
COVERAGE = Path('/var/lib/homelab-otel-history/coverage-20261031')
SOURCE = COVERAGE / 'preserved-target/01M66BZJJH7AX3HTZFRZD02SXP'
SHA = '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209'
BINARY_SHA = '9725e698476cbd4ab38f04c3481083067574fd580c479afdc57bfd4c3f8bab63'


def save(name, value):
    temp = BASE / (name + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(BASE / name)


def disk_reserve(extra=0):
    stat = os.statvfs(BASE)
    if stat.f_bavail * stat.f_frsize - extra < stat.f_blocks * stat.f_frsize // 5:
        raise ValueError('Current-history roundtrip would breach 20% filesystem reserve')


def run():
    os.umask(0o077)
    if os.geteuid() != 0 or (BASE / 'result.json').exists():
        raise ValueError('New protected historical roundtrip required')
    control = [line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')]
    if len(control) != 1:
        raise ValueError('Hard cgroup-v2 bounds required')
    group = Path('/sys/fs/cgroup') / control[0].lstrip('/')
    maximum = (group / 'memory.max').read_text().strip()
    quota, period = (group / 'cpu.max').read_text().split()
    if maximum == 'max' or int(maximum) > 3 * 1024**3 or (group / 'memory.swap.max').read_text().strip() != '0' or quota == 'max' or int(quota) > int(period) * 2:
        raise ValueError('Missing explicit memory/swap/CPU limits')
    with Path('/var/lib/homelab-otel-history/importer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = json.loads(Path('/home/alchemmist/.local/share/homelab/otel-history-recovery-20261031/result.json').read_text())
        if old.get('success') is not True:
            raise ValueError('Previous importer has not completed successfully')
        proof = json.loads((COVERAGE / 'target-integrity.json').read_text())
        if proof.get('healthyHostFullCanonicalInventoryVerified') is not True or proof.get('canonicalSHA256') != SHA or proof.get('samples') != 6383043932:
            raise ValueError('Complete trusted current-source canonical proof required')
        if not (SOURCE / 'meta.json').is_file() or any(path.is_symlink() for path in SOURCE.rglob('*')):
            raise ValueError('Preserved source block required without symlinks')
        binary = BASE / 'otel-history'
        with binary.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != BINARY_SHA:
                raise ValueError('Unpinned roundtrip executable')
        disk_reserve(72 * 1024**3)
        status = {'success': False, 'sourceSamples': 6383043932, 'sourceCanonicalSHA256': SHA,
                  'productionPublished': False, 'originalsDeleted': False, 'additionalLossApproved': False,
                  'startedAtUnix': time.time(), 'exportBudgetBytes': 56 * 1024**3}
        try:
            def execute(phase, arguments):
                save('progress.json', dict(status, phase=phase))
                with (BASE / (phase + '.stdout')).open('x') as output, (BASE / (phase + '.stderr')).open('x') as errors:
                    process = subprocess.Popen([str(binary), *arguments], stdout=output, stderr=errors, start_new_session=True,
                                               env=dict(os.environ, GOMAXPROCS='2', GOMEMLIMIT='2GiB'))
                    try:
                        while process.poll() is None:
                            disk_reserve(512 * 1024**2)
                            time.sleep(10)
                        if process.returncode:
                            raise subprocess.CalledProcessError(process.returncode, phase)
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGTERM)
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                os.killpg(process.pid, signal.SIGKILL)
                                process.wait(timeout=10)
            exported = WORK / 'otlp'
            execute('export', ['export', '--source', str(SOURCE), '--output', str(exported), '--max-bytes', str(56 * 1024**3)])
            manifest = json.loads((exported / 'manifest.json').read_text())
            if manifest['samples'] != 6383043932 or manifest['canonicalSHA256'] != SHA or manifest.get('completeSourceBlock') is not True:
                raise ValueError('Full source export differs from known approved repair')
            execute('import', ['import', '--source', str(exported), '--output', str(WORK / 'restored')])
            blocks = list((WORK / 'restored').glob('*/meta.json'))
            if len(blocks) != 1:
                raise ValueError('Exactly one canonical restored block required')
            execute('verify', ['verify', '--source', str(exported), '--block', str(blocks[0].parent)])
            status.update(success=True, restoredBlock=str(blocks[0].parent), fullCanonicalRoundtripVerified=True,
                          nativeThanosIndexAndQueryStillRequired=True)
        except Exception as error:
            status['errorType'] = type(error).__name__
            raise
        finally:
            status['finishedAtUnix'] = time.time()
            save('result.json', status)


if __name__ == '__main__':
    run()
