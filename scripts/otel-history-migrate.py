import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('history_archive', ROOT / 'scripts/otel-history-archive.py')
ARCHIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARCHIVE)
NATIVE_REASONS = ('native histogram samples require native preservation',
                  'timestamp cannot be represented by standard OTLP')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def atomic_json(path, document):
    temporary = path.with_name(path.name + '.partial')
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(document, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def covered(block, covers):
    cursor = block['minTime']
    for item in sorted(covers, key=lambda item: item['minTime']):
        if item['maxTime'] <= cursor:
            continue
        if item['minTime'] > cursor:
            return False
        cursor = max(cursor, item['maxTime'])
        if cursor >= block['maxTime']:
            return True
    return False


def classify_candidates(receipt):
    reports = receipt['reports']
    raw = reports['thanos-raw.tar.gz']['blocks']
    active_raw = [block for block in raw if block['resolution'] == 0 and not block['deletionMarked']]
    candidates = []
    native = []
    for archive, report in reports.items():
        for block in report['blocks']:
            record = {'archive': archive, **block}
            if block['resolution'] != 0:
                native.append({**record, 'reason': 'downsampled-native'})
            elif archive != 'prometheus-snapshot.tar.gz' and block['deletionMarked']:
                native.append({**record, 'reason': 'bucket-deletion-mark-preserved'})
            elif archive == 'prometheus-snapshot.tar.gz' and covered(block, [item for item in active_raw if item['ulid'] == block['ulid'] or block['ulid'] in item.get('compactionSources', [])]):
                native.append({**record, 'reason': 'snapshot-range-covered-by-active-thanos-raw'})
            else:
                candidates.append(record)
    return candidates, native


def prepare_workspace(path, receipt, resume):
    resolved = path.resolve()
    for forbidden in ('/var/lib', '/private/var/lib', '/host', '/etc', '/private/etc', '/srv'):
        if resolved == Path(forbidden) or Path(forbidden) in resolved.parents:
            raise ValueError('Production workspace paths are forbidden')
    identity = fingerprint(receipt)
    state_path = resolved / 'state.json'
    if resume:
        state = json.loads(state_path.read_text())
        if state['backupReceiptSHA256'] != identity:
            raise ValueError('Cannot resume a different backup receipt')
    else:
        resolved.mkdir(mode=0o700, parents=False, exist_ok=False)
        state = {'schemaVersion': 1, 'backupReceiptSHA256': identity,
                 'createdAt': datetime.now(timezone.utc).isoformat(),
                 'archives': {}, 'blocks': {}, 'complete': False, 'productionModified': False}
        atomic_json(state_path, state)
    return resolved, state


def extract_archive(source, expected_hash, destination, expected_report):
    report = ARCHIVE.verify_file(source, expected_hash)
    if report != expected_report:
        raise ValueError('Verified archive differs from receipt')
    if destination.exists():
        raise ValueError('Existing extraction requires explicit resume validation')
    destination.mkdir(mode=0o700)
    with tarfile.open(source, 'r:gz') as archive:
        for member in archive:
            if member.name == ARCHIVE.MANIFEST_NAME:
                continue
            archive.extract(member, destination, filter='data')
    with tarfile.open(source, 'r:gz') as archive:
        for member in archive:
            if member.name == ARCHIVE.MANIFEST_NAME:
                manifest = json.load(archive.extractfile(member))
                break
        else:
            raise ValueError('Archive manifest not found')
    atomic_json(destination / 'extraction-manifest.json', manifest)
    verify_extraction(destination, expected_report)


def verify_extraction(destination, report):
    manifest = json.loads((destination / 'extraction-manifest.json').read_text())
    if manifest['blocks'] != report['blocks']:
        raise ValueError('Extracted block inventory changed')
    expected_files = set(manifest['files'])
    observed_files = set()
    for block in report['blocks']:
        root = destination / block['ulid']
        if root.is_symlink() or not root.is_dir():
            raise ValueError('Invalid extracted block directory')
        for path in root.rglob('*'):
            if path.is_symlink():
                raise ValueError('Symlink in extracted block')
            if path.is_file():
                observed_files.add(path.relative_to(destination).as_posix())
    if observed_files != expected_files:
        raise ValueError('Extracted file inventory changed')
    for name, expected in manifest['files'].items():
        path = destination / name
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while data := stream.read(4 * 1024 ** 2):
                digest.update(data)
        if path.stat().st_size != expected['size'] or digest.hexdigest() != expected['sha256']:
            raise ValueError('Extracted file checksum mismatch')
    return True


def inventory_block(binary, source):
    result = subprocess.run([str(binary), 'capabilities', '--source', str(source)],
                            capture_output=True, text=True, timeout=900)
    if result.returncode:
        reason = result.stderr.strip()
        if reason in NATIVE_REASONS:
            return {'status': 'native-exception', 'reason': reason}
        raise RuntimeError('TSDB inventory failed: ' + reason[-1000:])
    inventory = json.loads(result.stdout)
    if inventory['samplesInChunks'] <= 0 or not inventory['standardOTLPRepresentable']:
        raise ValueError('Raw block has no query-visible samples')
    return {'status': 'representable', 'inventory': inventory}


def finish_existing_import(binary, exported, imported, source_block, timeout=3600):
    manifest = json.loads((exported / 'manifest.json').read_text())
    if manifest['sourceMeta']['ulid'] != source_block['ulid'] or not manifest['completeSourceBlock']:
        raise ValueError('Interrupted roundtrip is not a complete export of this source block')
    blocks = [path for path in imported.iterdir() if path.is_dir() and len(path.name) == 26 and (path / 'meta.json').is_file()]
    if len(blocks) != 1:
        raise ValueError('Interrupted import does not contain exactly one completed block; inspection is required')
    block = blocks[0]
    subprocess.run([str(binary), 'verify', '--source', str(exported), '--block', str(block)], check=True, timeout=timeout)
    verification = {
        'verified': True, 'samples': manifest['samples'], 'canonicalSHA256': manifest['canonicalSHA256'],
        'block': block.name, 'productionModified': False, 'staleMarkers': manifest.get('staleMarkers', 0),
        'metricSelection': manifest.get('metricSelection', ''), 'completeSourceBlock': True,
    }
    receipt_path = imported / 'verification.json'
    if receipt_path.exists():
        if json.loads(receipt_path.read_text()) != verification:
            raise ValueError('Existing import receipt differs from verified content')
    else:
        atomic_json(receipt_path, verification)
    return verification


def require_disk(path, projected):
    filesystem = os.statvfs(path)
    available = filesystem.f_bavail * filesystem.f_frsize
    total = filesystem.f_blocks * filesystem.f_frsize
    reserve = total // 5
    if available - projected < reserve:
        raise ValueError(f'Workspace capacity insufficient: {available} available, {projected} projected, {reserve} reserved')


@contextmanager
def workspace_lock(workspace):
    descriptor = os.open(workspace / '.migration.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another migration worker owns this workspace') from error
        os.ftruncate(descriptor, 0)
        os.write(descriptor, str(os.getpid()).encode())
        yield
    finally:
        os.close(descriptor)


def migrate(binary, backup, receipt, workspace, resume, max_bytes, classify_only, max_blocks=None, revalidate_classifier=False, command_timeout=3600, resume_partial_exports=False):
    if not receipt.get('verified') or not receipt.get('snapshotIncludesHead') or not receipt.get('controllerStateRestored'):
        raise ValueError('A verified, head-inclusive backup with restored controllers is required')
    workspace, _ = prepare_workspace(workspace, receipt, resume)
    with workspace_lock(workspace):
        workspace, state = prepare_workspace(workspace, receipt, True)
        return migrate_workspace(binary, backup, receipt, workspace, state, max_bytes, classify_only,
                                 max_blocks, revalidate_classifier, command_timeout, resume_partial_exports)


def migrate_workspace(binary, backup, receipt, workspace, state, max_bytes, classify_only,
                      max_blocks, revalidate_classifier, command_timeout, resume_partial_exports):
    state_path = workspace / 'state.json'
    expected_archives = {'prometheus-snapshot.tar.gz', 'thanos-raw.tar.gz', 'thanos-5m.tar.gz', 'thanos-1h.tar.gz'}
    if set(receipt['reports']) != expected_archives or set(receipt['archiveSha256']) != expected_archives:
        raise ValueError('Backup archive inventory is incomplete')
    for name in sorted(expected_archives):
        source = backup / name
        destination = workspace / name.removesuffix('.tar.gz')
        if state['archives'].get(name, {}).get('verified'):
            verify_extraction(destination, receipt['reports'][name])
        else:
            require_disk(workspace, receipt['reports'][name]['bytes'])
            print('Verifying and extracting ' + name, flush=True)
            extract_archive(source, receipt['archiveSha256'][name], destination, receipt['reports'][name])
            state['archives'][name] = {'verified': True, 'sha256': receipt['archiveSha256'][name]}
            atomic_json(state_path, state)
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    if state.get('classifierBinarySHA256') != binary_hash:
        completed = {key: item for key, item in state['blocks'].items() if item.get('status') == 'roundtrip-verified'}
        if completed:
            if not revalidate_classifier:
                raise ValueError('Completed roundtrips require --revalidate-classifier before changing the classifier binary')
            for item in completed.values():
                subprocess.run([str(binary), 'verify', '--source', item['export'], '--block', item['restoredBlock']], check=True, timeout=command_timeout)
        state['blocks'] = completed
        state['classifierBinarySHA256'] = binary_hash
        atomic_json(state_path, state)
    classification_receipt = json.loads(json.dumps(receipt))
    for name, report in classification_receipt['reports'].items():
        for item in report['blocks']:
            metadata = json.loads((workspace / name.removesuffix('.tar.gz') / item['ulid'] / 'meta.json').read_text())
            item['compactionSources'] = metadata.get('compaction', {}).get('sources', [])
    candidates, native = classify_candidates(classification_receipt)
    state['preservedNative'] = native
    output = workspace / 'roundtrip'
    output.mkdir(mode=0o700, exist_ok=True)
    completed_now = 0
    for block in candidates:
        key = block['archive'] + '/' + block['ulid']
        previous = state['blocks'].get(key)
        if previous and previous['status'] in ('native-exception', 'roundtrip-verified'):
            if previous['status'] == 'roundtrip-verified':
                subprocess.run([str(binary), 'verify', '--source', previous['export'], '--block', previous['restoredBlock']], check=True, timeout=command_timeout)
            continue
        source = workspace / block['archive'].removesuffix('.tar.gz') / block['ulid']
        print('Classifying raw block ' + block['ulid'], flush=True)
        result = inventory_block(binary, source)
        state['blocks'][key] = {**block, **result}
        atomic_json(state_path, state)
        if result['status'] == 'native-exception' or classify_only:
            continue
        source_bytes = sum(path.stat().st_size for path in source.rglob('*') if path.is_file())
        require_disk(workspace, max_bytes + 2 * source_bytes)
        prefix = block['archive'].split('.')[0] + '-' + block['ulid']
        exported = output / (prefix + '-otlp')
        imported = output / (prefix + '-restored')
        if exported.exists() and imported.exists():
            verification = finish_existing_import(binary, exported, imported, block, command_timeout)
        elif imported.exists():
            raise ValueError('Interrupted import without its export requires inspection')
        else:
            if exported.exists() and (exported / 'manifest.json').exists():
                manifest = json.loads((exported / 'manifest.json').read_text())
                if manifest['sourceMeta']['ulid'] != block['ulid'] or not manifest['completeSourceBlock']:
                    raise ValueError('Existing export does not cover this complete source block')
            else:
                command = [str(binary), 'export', '--source', str(source), '--output', str(exported), '--max-bytes', str(max_bytes)]
                if exported.exists():
                    if not resume_partial_exports:
                        raise ValueError('Partial export requires explicit --resume-partial-exports')
                    command.append('--resume')
                state['currentOperation'] = {'phase': 'resume-export' if exported.exists() else 'export', 'block': block['ulid'],
                                             'startedAt': datetime.now(timezone.utc).isoformat(), 'workerPID': os.getpid()}
                atomic_json(state_path, state)
                subprocess.run(command, check=True, timeout=command_timeout)
            state['currentOperation'] = {'phase': 'import', 'block': block['ulid'],
                                         'startedAt': datetime.now(timezone.utc).isoformat(), 'workerPID': os.getpid()}
            atomic_json(state_path, state)
            subprocess.run([str(binary), 'import', '--source', str(exported), '--output', str(imported)], check=True, timeout=command_timeout)
            verification = json.loads((imported / 'verification.json').read_text())
        if not verification['verified'] or not verification['completeSourceBlock']:
            raise ValueError('Incomplete block roundtrip')
        state['blocks'][key].update(status='roundtrip-verified', export=str(exported),
                                    restoredBlock=str(imported / verification['block']), verification=verification)
        atomic_json(state_path, state)
        completed_now += 1
        if max_blocks is not None and completed_now >= max_blocks:
            break
    state.pop('currentOperation', None)
    state['classificationComplete'] = len(state['blocks']) == len(candidates)
    state['complete'] = state['classificationComplete'] and all(item['status'] in ('native-exception', 'roundtrip-verified') for item in state['blocks'].values())
    state['nativeExceptionCount'] = sum(item['status'] == 'native-exception' for item in state['blocks'].values())
    state['roundtripVerifiedCount'] = sum(item['status'] == 'roundtrip-verified' for item in state['blocks'].values())
    state['allHistoryConvertedToOTLP'] = state['complete'] and not native and state['nativeExceptionCount'] == 0
    atomic_json(state_path, state)
    print(json.dumps({key: state[key] for key in ('classificationComplete', 'complete', 'nativeExceptionCount', 'roundtripVerifiedCount', 'allHistoryConvertedToOTLP', 'productionModified')}, indent=2))
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, default=ROOT / 'deploy/monitoring/migration-evidence/backup-20261028.json')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--max-bytes-per-block', type=int, default=4 * 1024 ** 3)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--classify-only', action='store_true')
    parser.add_argument('--max-blocks', type=int)
    parser.add_argument('--revalidate-classifier', action='store_true')
    parser.add_argument('--command-timeout-seconds', type=int, default=3600)
    parser.add_argument('--resume-partial-exports', action='store_true')
    args = parser.parse_args()
    try:
        if args.max_blocks is not None and (args.max_blocks <= 0 or args.classify_only):
            raise ValueError('max-blocks must be positive and is only valid for roundtrips')
        if args.command_timeout_seconds <= 0:
            raise ValueError('Command timeout must be positive')
        if args.max_bytes_per_block <= 0:
            raise ValueError('Export byte budget must be positive')
        migrate(args.binary.resolve(), args.backup.resolve(), json.loads(args.receipt.read_text()),
                args.workspace, args.resume, args.max_bytes_per_block, args.classify_only, args.max_blocks, args.revalidate_classifier, args.command_timeout_seconds, args.resume_partial_exports)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
