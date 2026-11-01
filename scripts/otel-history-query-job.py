"""Finite stock-Thanos checks of completed isolated normalized raw-history outputs.

Does not publish blocks, rewrite external labels, or start another importer.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shlex
import shutil
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
THANOS_SHA = 'e88cf130a15f91ba8437885231fd3aa27fe88ef118b1fa2f2251465a526c7df9'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, document):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(document, indent=2) + '\n')
    temporary.replace(path)


def run(args):
    os.umask(0o077)
    args.output.mkdir(mode=0o700, exist_ok=False)
    anchor_sha = sha(args.anchors)
    if sha(args.thanos) != THANOS_SHA:
        raise ValueError('Unpinned upstream native binary')
    initial = json.loads(args.initial_result.read_text())
    if initial.get('verified') is not True:
        raise ValueError('Initial native check did not pass')
    report = {'startedAt': datetime.now(timezone.utc).isoformat(), 'productionModified': False,
              'migrationCompleted': False, 'success': False, 'verified': initial.get('priorVerified', {initial['block']: initial}),
              'blocked': {}, 'anchorBinarySHA256': anchor_sha}
    if any(item.get('verified') is not True or item.get('nativeBinarySHA256') != THANOS_SHA for item in report['verified'].values()):
        raise ValueError('Prior native checks must each be independently verified and pinned')
    environment = {**os.environ, 'ANSIBLE_NOCOLOR': '1', 'ANSIBLE_SSH_EXECUTABLE': '/tmp/otel-migration-ssh/bin/ssh'}
    try:
        for cycle in range(48):
            state = json.loads(args.state.read_text())
            if args.source_result.exists() and json.loads(args.source_result.read_text()).get('success') is not True:
                raise RuntimeError('Source history job failed; dependent checks stop')
            normalized = {}
            initial_metadata = json.loads(args.initial_metadata.read_text())
            for receipt in initial_metadata['completed']:
                normalized[receipt['block']] = receipt
            if args.normalization_progress.exists():
                for receipt in json.loads(args.normalization_progress.read_text())['completed'].values():
                    normalized[receipt['block']] = receipt
            for key, item in state['blocks'].items():
                if item.get('status') != 'roundtrip-verified':
                    continue
                block_id = Path(item['restoredBlock']).name
                if block_id in report['verified'] or key in report['blocked'] or block_id not in normalized:
                    continue
                if not re.fullmatch(r'[0-9A-HJKMNP-TV-Z]{26}', item['ulid']):
                    raise ValueError('Invalid source block identity')
                receipt = normalized[block_id]
                if receipt.get('verified') is not True or receipt.get('nativePhysicalMetadataVerified') is not True:
                    raise ValueError('Unverified native metadata receipt')
                if receipt['canonicalSHA256'] != item['verification']['canonicalSHA256'] or receipt['samples'] != item['verification']['samples']:
                    raise ValueError('Source and normalization canonical receipts differ')
                candidates = [args.initial_root / (item['ulid'] + '-normalized') / block_id,
                              args.normalization_root / (item['ulid'] + '-normalized') / block_id]
                block = next((path for path in candidates if path.is_dir()), None)
                if block is None:
                    raise ValueError('Completed normalized output is absent')
                metadata = json.loads((block / 'meta.json').read_text())
                if not metadata.get('thanos', {}).get('labels'):
                    report['blocked'][key] = 'external Thanos snapshot context must be established independently; no labels invented'
                    continue
                if sha(args.anchors) != anchor_sha:
                    raise ValueError('Pinned anchor selector binary changed')
                local = args.output / item['ulid']
                local.mkdir(mode=0o700)
                with (local / 'anchors.json').open('x') as stream:
                    subprocess.run([str(args.anchors), '--block', str(block)], stdout=stream, check=True, timeout=120)
                request = json.loads((local / 'anchors.json').read_text())
                native_bytes = sum(path.stat().st_size for path in block.rglob('*') if path.is_file())
                disk = shutil.disk_usage(local)
                if disk.free - native_bytes - 1024**3 < disk.total // 5:
                    raise ValueError('Native archive would breach controller 20% disk reserve')
                with tarfile.open(local / 'candidate.tar', 'x') as archive:
                    archive.add(block, arcname=block.name)
                request.update(archiveSHA256=sha(local / 'candidate.tar'), archiveBytes=(local / 'candidate.tar').stat().st_size,
                               nativeBinarySHA256=THANOS_SHA)
                write(local / 'request.json', request)
                nonce = item['ulid'].lower()
                stage = '/home/alchemmist/.cache/otel-native-compat-' + nonce
                remote = '/var/tmp/otel-history-native-compat-' + nonce
                with (local / 'transfer.log').open('x') as log:
                    subprocess.run(['ssh', '-F', str(args.ssh_config), '-o', 'BatchMode=yes', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4', 'socrat-1', shlex.join(['mkdir', '-m', '700', '-p', stage])], stdout=log, stderr=log, check=True, timeout=30)
                    subprocess.run(['scp', '-F', str(args.ssh_config), '-o', 'BatchMode=yes', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4', str(local / 'candidate.tar'), str(args.thanos), 'socrat-1:' + stage + '/'], stdout=log, stderr=log, check=True, timeout=1800)
                # scp preserves the supplied binary basename; verifier requires exactly 'thanos'.
                if args.thanos.name != 'thanos':
                    raise ValueError('Pinned native executable must have basename thanos')
                variables = {'ansible_host': 'socrat-1', 'otel_native_compat_root': remote,
                             'otel_native_compat_stage': stage, 'otel_native_compat_local': str(local),
                             'otel_native_compat_nonce': nonce}
                write(local / 'vars.json', variables)
                with (local / 'ansible.log').open('x') as log:
                    subprocess.run(['ansible-playbook', '-i', 'inventory/hosts.yml', 'playbooks/otel-history-native-compat.yml',
                                    '-e', '@' + str(local / 'vars.json'), '-e', '@' + str(args.become_vars)],
                                   cwd=ROOT / 'ansible', env=environment, stdout=log, stderr=log, check=True, timeout=1320)
                checked = json.loads((local / 'result.json').read_text())
                if checked.get('verified') is not True or checked['block'] != block_id:
                    raise ValueError('Native compatibility receipt does not match completed source')
                report['verified'][block_id] = checked
                write(args.output / 'progress.json', report)
            write(args.output / 'progress.json', report)
            if args.normalization_result.exists():
                completed = json.loads(args.normalization_result.read_text())
                if completed.get('success') is not True:
                    raise RuntimeError('Normalization failed')
                if state.get('complete') is True:
                    report['success'] = True
                    report['allHistoricalQueryContextsVerified'] = not report['blocked']
                    break
            if cycle < 47:
                time.sleep(1800)
        else:
            report['stopReason'] = 'bounded-check-window-ended; no completion inferred'
    except Exception as error:
        report['errorType'] = type(error).__name__
        raise
    finally:
        report['finishedAt'] = datetime.now(timezone.utc).isoformat()
        write(args.output / 'result.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('state', 'source-result', 'normalization-root', 'normalization-progress', 'normalization-result',
                 'initial-metadata', 'initial-root', 'initial-result', 'anchors', 'thanos', 'ssh-config', 'become-vars', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    run(parser.parse_args())
