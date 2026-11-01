"""Finite nine-block legacy-tail roundtrip queue; no production publication.

Waits for current native finalization and all six original comparisons. Holds the
single-importer lock. Uses only pinned stock tools and exact full canonical-v1
checks. Originals/failed artifacts are never deleted. Only verified temporary
transport/OTLP copies are cleaned after protected native staging succeeds.
"""
import argparse
import gzip
import socket
import fcntl
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import tarfile
import time

BASE = Path('/var/lib/homelab-otel-history/tail-roundtrip-20261101')
WORK = Path('/home/alchemmist/otel-tail-roundtrip-work-20261101')
INPUT = Path('/home/alchemmist/.local/share/homelab/otel-tail-input-20261101')
GOLDEN = Path('/home/alchemmist/.local/share/homelab/otel-golden-sources-20261101')
CURRENT = Path('/var/lib/homelab-otel-history/current-native-finalize-20261031/final-result.json')
GO_PIN = 'c2b4fd258ebffb1f31d9caec4c05cbc803dce52b0365fb69f7efa74ba411a077'
THANOS_PIN = 'e88cf130a15f91ba8437885231fd3aa27fe88ef118b1fa2f2251465a526c7df9'
ARCHIVE_PIN = '64d364074f13f6977cdc92f9117181340563c217f68de92a85c6cd5e6b48bac5'


PROFILES = {
    'conservative': {'memoryBytes': 3 * 1024**3, 'cpus': 2, 'gomaxprocs': '2', 'gomemlimit': '2GiB'},
    'socrat0-fast': {'memoryBytes': 9 * 1024**3, 'cpus': 16, 'exportWorkers': 50, 'gomaxprocs': '16', 'gomemlimit': '6GiB'},
}
RESOURCE = PROFILES['conservative']


def execution_profile(name, hostname):
    if name not in PROFILES or (name == 'socrat0-fast' and hostname != 'socrat-0'):
        raise ValueError('Fast historical replay is explicitly restricted to trusted socrat-0')
    return PROFILES[name]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(name, value):
    temp = BASE / (name + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(BASE / name)


def reserve(extra=0):
    disk = shutil.disk_usage(WORK)
    if disk.free - extra < disk.total // 5:
        raise ValueError('Tail queue would breach 20% filesystem reserve')


def prerequisites(current, golden):
    if current.get('success') is not True or current.get('actualNativeThanosQueryVerified') is not True or current.get('durableStagingVerified') is not True or current.get('samples') != 6383043932 or current.get('canonicalSHA256') != '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209':
        raise ValueError('Current repaired-block canonical/native/durable proof required')
    expected = {4606695568: 'd49a8367a81cdd9dfd626fdf13eded48063abdb37289669d5572a8f8c3821b1f',
                5955368159: '968bcb72e212318421325cf79f572066784c63433aa7d20ab60f0061ebbaaf43',
                6137437488: 'aa43a0def61cd41d34336f6f68b2dae516aed8574d52b1513a6e82aa42280e81',
                260844250: '9da8f16dc720a85adf1a3c37ddf9cc8956b2c0121aa5b3668671d735f65d2790',
                261337432: '14ac7b9f5acb7a25cd869bcf07103d2ca03096ca6e67bb02e20b4fc2d8780856',
                1043291602: '96b0b9f5f763ec154578de90b490a13683a81f42bae32c634118c8b356189acf'}
    if len(golden) != 6 or {item.get('samples'): item.get('canonicalSHA256') for item in golden} != expected or any(item.get('success') is not True or item.get('fullOriginalToRestoredCanonicalEqualityVerified') is not True or item.get('sourceArchiveSHA256') != 'fc0f73919caa2615441e0053b632d6b48b087d5542bcc2c39c688267cea48632' for item in golden):
        raise ValueError('All six exact original-to-restored comparisons required')


def clean_verified_current_encoding():
    """Remove only successful encoded transport copies, never native history."""
    original = Path('/home/alchemmist/otel-history-current-roundtrip-work-20261031/otlp')
    sealed = CURRENT.parent / 'canonical-manifest.json'
    if not original.is_dir() or original.is_symlink() or not sealed.is_file() or sha(original / 'manifest.json') != sha(sealed):
        raise ValueError('Verified current OTLP transport manifest is not sealed')
    manifest = json.loads(sealed.read_text())
    if manifest.get('samples') != 6383043932 or manifest.get('canonicalSHA256') != '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209' or manifest.get('completeSourceBlock') is not True:
        raise ValueError('Refuse cleanup of unverified current transport encoding')
    shutil.rmtree(original)
    save('current-verified-encoding-cleanup.json', {'onlyVerifiedTemporaryOtlpEncodingRemoved': True,
         'originalHistoryDeleted': False, 'sealedManifestRetained': str(sealed), 'productionModified': False})


def validate_source_names(blocks):
    names = [block['ulid'] for block in blocks]
    expected = {'01M66G9HT3YJ4W6TSADWG305M6', '01M67BSZ1EMNPWMQ4SYBNEYJ8H',
                '01M6878TK453MC40ASW9ZAJ0HX', '01M68SVKT78T25E55SH643YFM0',
                '01M690QA5VG8VBK01AAHD34GT9', '01M690QQG8K9TQ5WBE7W573CW0',
                '01M692QSEEXSXA6G4TRR7SXEWC', '01M697K1G59F78YWVGT9Y2K08Z',
                '01M697KFH379N839ZYW5VM28J5'}
    if len(names) != 9 or set(names) != expected or any(not re.fullmatch(r'[0-9A-HJKMNP-TV-Z]{26}', name) for name in names):
        raise ValueError('Only the exact frozen nine-source identities are permitted')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def execute(root, phase, arguments):
    with (root / (phase + '.stdout')).open('x') as output, (root / (phase + '.stderr')).open('x') as errors:
        process = subprocess.Popen(arguments, stdout=output, stderr=errors, start_new_session=True,
                                   env=dict(os.environ, GOMAXPROCS=RESOURCE['gomaxprocs'], GOMEMLIMIT=RESOURCE['gomemlimit']))
        deadline = time.monotonic() + 14400
        try:
            while process.poll() is None:
                reserve(512 * 1024**2)
                if time.monotonic() >= deadline:
                    raise TimeoutError('Tail queue phase exceeded finite 4h deadline')
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


def validate_export_resume(progress, previous):
    if (progress.get('phase') != 'export' or progress.get('completedBlocks') != 0
            or progress.get('originalBlock') != '01M66G9HT3YJ4W6TSADWG305M6'
            or previous.get('success') is not False or previous.get('blocks') != []
            or previous.get('sourceArchiveSHA256') != ARCHIVE_PIN):
        raise ValueError('Only interrupted first-block export with no imports may resume')


def prepare_export_resume():
    progress = json.loads((BASE / 'progress.json').read_text())
    previous = json.loads((BASE / 'result.json').read_text())
    validate_export_resume(progress, previous)
    root = WORK / progress['originalBlock']
    if (root / 'restored').exists() or (BASE / progress['originalBlock']).exists():
        raise ValueError('Import/native stage already exists; inspect rather than resume')
    inventory = json.loads((root / 'inventory.stdout').read_text())
    if not inventory.get('canonicalSHA256') or inventory.get('samples', 0) <= 0:
        raise ValueError('Completed full original inventory required')
    output = root / 'otlp'
    if not output.is_dir() or output.is_symlink():
        raise ValueError('Private partial export required')
    suffix = str(time.time_ns())
    # Serial predecessor can leave at most its last open batch incomplete. Keep
    # that transport artifact privately, never delete originals or valid batches.
    batches = sorted(output.glob('*.otlp.pb.gz'))
    if batches and not (output / 'manifest.json').exists():
        last = batches[-1]
        if last.is_symlink() or not last.is_file():
            raise ValueError('Unexpected interrupted batch type')
        try:
            with gzip.open(last, 'rb') as stream:
                size = 0
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > 32 * 1024**2:
                        raise ValueError('Interrupted batch exceeds protobuf bound')
        except (EOFError, OSError):
            quarantine = root / ('interrupted-transport-' + suffix)
            quarantine.mkdir(mode=0o700)
            last.rename(quarantine / last.name)
    for phase in ['export']:
        for extension in ['stdout', 'stderr']:
            source = root / (phase + '.' + extension)
            if source.exists():
                source.rename(root / (phase + '.interrupted-' + suffix + '.' + extension))
    (BASE / 'result.json').rename(BASE / ('result.interrupted-export-' + suffix + '.json'))
    save('parallel-resume-receipt.json', {'originalBlock': progress['originalBlock'],
         'previousRun': previous, 'resumeRequiresEveryExistingBatchMatchOriginal': True,
         'originalHistoryDeleted': False, 'preparedAtUnix': time.time()})


def prepare_import_resume():
    progress = json.loads((BASE / 'progress.json').read_text())
    previous = json.loads((BASE / 'result.json').read_text())
    validate_export_resume(dict(progress, phase='export'), previous)
    if progress.get('phase') != 'import':
        raise ValueError('Only the interrupted first import may adopt a verified native prefix')
    root = WORK / progress['originalBlock']
    if (root / 'restored-fast').exists() or (BASE / progress['originalBlock']).exists():
        raise ValueError('Existing fast/native output requires inspection')
    proof = json.loads((BASE / 'import-prefix-proof-v1.json').read_text())
    if (proof.get('verified') is not True or proof.get('version') != 1
            or proof.get('source') != str(root / 'otlp') or proof.get('samples', 0) <= 0
            or proof.get('manifestSHA256') != sha(root / 'otlp/manifest.json')):
        raise ValueError('Exact full source/native prefix proof required')
    suffix = str(time.time_ns())
    for extension in ['stdout', 'stderr']:
        source = root / ('import.' + extension)
        if source.exists():
            source.rename(root / ('import.interrupted-' + suffix + '.' + extension))
    (BASE / 'result.json').rename(BASE / ('result.interrupted-import-' + suffix + '.json'))
    save('pipeline-resume-receipt.json', {'verifiedPrefixSamples': proof['samples'],
         'verifiedPrefixShards': len(proof['shards']), 'priorRun': previous,
         'oldImportAndUnadoptedShardsRetained': True, 'originalHistoryDeleted': False})


def run(profile='conservative', resume_export=False, resume_import=False):
    if os.geteuid() != 0:
        raise ValueError('Protected root queue required')
    with (BASE.parent / 'importer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_locked(profile, resume_export, resume_import)


def run_locked(profile='conservative', resume_export=False, resume_import=False):
    if resume_export and resume_import:
        raise ValueError('Choose exactly one explicit resume mode')
    resuming = resume_export or resume_import
    global RESOURCE
    RESOURCE = execution_profile(profile, socket.gethostname())
    os.umask(0o077)
    if os.geteuid() != 0 or ((BASE / 'result.json').exists() and not resuming):
        raise ValueError('New protected root queue required')
    groups = [line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')]
    if len(groups) != 1:
        raise ValueError('Hard cgroup v2 bounds required')
    group = Path('/sys/fs/cgroup') / groups[0].lstrip('/')
    memory = (group / 'memory.max').read_text().strip()
    quota, period = (group / 'cpu.max').read_text().split()
    if memory == 'max' or int(memory) > RESOURCE['memoryBytes'] or (group / 'memory.swap.max').read_text().strip() != '0' or quota == 'max' or int(quota) > RESOURCE['cpus'] * int(period):
        raise ValueError('Hard memory/swap/CPU bounds missing')
    status = {'success': False, 'productionPublished': False, 'originalHistoryDeleted': False,
              'sourceArchiveSHA256': ARCHIVE_PIN, 'blocks': [], 'startedAtUnix': time.time(), 'executionProfile': profile, 'resourceBudget': RESOURCE}
    try:
        deadline = time.monotonic() + 108000
        refs = json.loads((GOLDEN / 'references.json').read_text())['references']
        while True:
            receipts = [GOLDEN / 'receipts' / (block + '.json') for block in refs]
            if CURRENT.exists() and json.loads(CURRENT.read_text()).get('success') is not True:
                raise ValueError('Prior native finalization failed; preserve and inspect')
            if any(path.exists() and json.loads(path.read_text()).get('success') is not True for path in receipts):
                raise ValueError('Original-source comparison failed; preserve and inspect')
            copied_archive = INPUT / 'legacy-tail.tar'
            archive_ready = copied_archive.is_file() and copied_archive.stat().st_size == 3576514560
            if CURRENT.exists() and archive_ready and all(path.exists() for path in receipts):
                prerequisites(json.loads(CURRENT.read_text()), [json.loads(path.read_text()) for path in receipts])
                break
            save('progress.json', {'phase': 'await-current-native-and-six-original-comparisons', 'completedBlocks': 0})
            if time.monotonic() >= deadline:
                raise TimeoutError('Prior canonical/native prerequisites did not finish')
            time.sleep(30)
        binary = BASE / 'otel-history'
        tools = json.loads((BASE / 'tools.json').read_text())
        if sha(binary) != GO_PIN or sha(BASE / 'thanos') != THANOS_PIN or sha(BASE / 'anchors') != tools['anchors']:
            raise ValueError('Pinned queue/native tools differ')
        capture = json.loads((INPUT / 'capture.json').read_text())
        replica = json.loads((INPUT / 'verification.json').read_text())
        if replica.get('verified') is not True or replica.get('archiveSHA256') != ARCHIVE_PIN or capture.get('archiveSHA256') != ARCHIVE_PIN or len(capture['blocks']) != 9 or sum(block['stats']['numSamples'] for block in capture['blocks']) != 4170768866:
            raise ValueError('Frozen complete nine-block archive proof required')
        validate_source_names(capture['blocks'])
        archive = INPUT / 'legacy-tail.tar'
        if archive.is_symlink() or archive.stat().st_size != capture['archiveBytes'] or sha(archive) != ARCHIVE_PIN:
            raise ValueError('Whole healthy-host archive transfer verification failed')
        if resuming:
            cleanup = json.loads((BASE / 'current-verified-encoding-cleanup.json').read_text())
            if cleanup.get('onlyVerifiedTemporaryOtlpEncodingRemoved') is not True:
                raise ValueError('Prior completed-current cleanup proof required')
        else:
            clean_verified_current_encoding()
        compatibility = module('tail_native', BASE / 'compat.py')
        durable = module('tail_durable', BASE / 'durable.py')
        if resume_export:
            prepare_export_resume()
        if resume_import:
            prepare_import_resume()
        for original in capture['blocks']:
            name = original['ulid']
            root = WORK / name
            reuse = resuming and name == '01M66G9HT3YJ4W6TSADWG305M6'
            if not reuse:
                root.mkdir(mode=0o700)
                selected = 0
                reserve(20 * 1024**3)
                with tarfile.open(archive, 'r:') as source:
                    for member in source:
                        path = PurePosixPath(member.name)
                        if not path.parts or path.parts[0] != name:
                            continue
                        if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                            raise ValueError('Unsafe frozen source member')
                        selected += member.size
                        if selected > 7 * 1024**3:
                            raise ValueError('Single source exceeds extraction budget')
                        source.extract(member, root / 'source', filter='data')
            block = root / 'source' / name
            meta = json.loads((block / 'meta.json').read_text())
            if any(meta.get(key) != original.get(key) for key in ['ulid', 'minTime', 'maxTime', 'stats', 'compaction']) or meta.get('thanos', {}).get('labels', {}) != original['externalLabels']:
                raise ValueError('Original source semantic context differs')
            def phase(label, arguments):
                save('progress.json', {'phase': label, 'originalBlock': name, 'completedBlocks': len(status['blocks'])})
                execute(root, label, [str(binary), *arguments])
            if not reuse:
                phase('inventory', ['inventory', '--source', str(block)])
            inventory = json.loads((root / 'inventory.stdout').read_text())
            if inventory['samples'] != original['stats']['numSamples']:
                raise ValueError('Full source sample inventory differs')
            if not (reuse and (root / 'otlp/manifest.json').is_file()):
                phase('export', ['export', '--source', str(block), '--output', str(root / 'otlp'),
                      '--max-bytes', str(10 * 1024**3), '--export-workers', str(RESOURCE.get('exportWorkers', RESOURCE['cpus']))]
                      + (['--resume'] if reuse else []))
            manifest = json.loads((root / 'otlp/manifest.json').read_text())
            if manifest['samples'] != inventory['samples'] or manifest['canonicalSHA256'] != inventory['canonicalSHA256'] or manifest.get('completeSourceBlock') is not True:
                raise ValueError('Export is not an exact full original')
            adopting = resume_import and name == '01M66G9HT3YJ4W6TSADWG305M6'
            restored_directory = root / ('restored-fast' if adopting else 'restored')
            phase('import', ['import', '--source', str(root / 'otlp'), '--output', str(restored_directory)]
                  + (['--resume-import-proof', str(BASE / 'import-prefix-proof-v1.json')] if adopting else []))
            restored = list(restored_directory.glob('*/meta.json'))
            if len(restored) != 1:
                raise ValueError('Exactly one restored source block required')
            target = restored[0].parent
            phase('verify', ['verify', '--source', str(root / 'otlp'), '--block', str(target)])
            stage = BASE / name
            stage.mkdir(mode=0o700)
            reserve(sum(path.stat().st_size for path in target.rglob('*') if path.is_file()) * 3)
            with tarfile.open(stage / 'candidate.tar', 'x') as output:
                output.add(target, arcname=target.name)
            shutil.copyfile(BASE / 'thanos', stage / 'thanos')
            anchors = json.loads(subprocess.run([str(BASE / 'anchors'), '--block', str(target)], check=True, capture_output=True, text=True, timeout=120).stdout)
            anchors.update(archiveSHA256=sha(stage / 'candidate.tar'), archiveBytes=(stage / 'candidate.tar').stat().st_size, nativeBinarySHA256=THANOS_PIN)
            native = Path('/var/tmp') / ('otel-history-native-compat-tail-20261101-' + name)
            native.mkdir(mode=0o700)
            (native / 'request.json').write_text(json.dumps(anchors))
            checked = compatibility.run(native, stage)
            if checked.get('verified') is not True:
                raise ValueError('Pinned native Store/Query failed')
            destination = Path('/var/lib/homelab-otel-history/staged') / target.name
            destination.mkdir(mode=0o700)
            before = durable.regular_inventory(native / 'bucket')
            if (native / 'bucket').stat().st_dev != destination.stat().st_dev:
                raise ValueError('Native staging must use same-filesystem rename')
            os.rename(native / 'bucket', destination / 'bucket')
            if before != durable.regular_inventory(destination / 'bucket'):
                raise ValueError('Verified staged native body changed')
            for filename in ['request.json', 'result.json']:
                shutil.copyfile(native / filename, destination / filename)
            receipt = {'block': target.name, 'durableDirectory': str(destination), 'fileCount': len(before),
                       'fileBytes': sum(value[2] for value in before.values()),
                       'originalBlock': name, 'restoredBlock': target.name, 'samples': inventory['samples'],
                       'canonicalSHA256': inventory['canonicalSHA256'], 'actualNativeThanosQueryVerified': True,
                       'durableStagingVerified': True, 'sameFilesystemRenameVerified': True,
                       'productionPublished': False, 'originalHistoryDeleted': False}
            (destination / 'durability.json').write_text(json.dumps(receipt, indent=2) + '\n')
            shutil.copyfile(root / 'inventory.stdout', stage / 'source-inventory.json')
            shutil.copyfile(root / 'otlp/manifest.json', stage / 'manifest.json')
            status['blocks'].append(receipt)
            save('canonical-progress.json', status)
            # Only generated, fully verified temporary copies; all originals
            # remain in the immutable archives, protected staged body and live store.
            for temporary in ['otlp', restored_directory.name, 'source']:
                shutil.rmtree(root / temporary)
        status['success'] = True
    except Exception as error:
        status['errorType'] = type(error).__name__
        raise
    finally:
        status['finishedAtUnix'] = time.time()
        result_name = ('resume-attempt-failed-' + str(time.time_ns()) + '.json'
                       if resuming and (BASE / 'result.json').exists() else 'result.json')
        save(result_name, status)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execution-profile', choices=list(PROFILES), default='conservative')
    parser.add_argument('--resume-export', action='store_true')
    parser.add_argument('--resume-import', action='store_true')
    args = parser.parse_args()
    run(args.execution_profile, args.resume_export, args.resume_import)
