"""Finite root finalizer: native-check and durably stage the last verified recovery.

Waits for the one predefined importer, never starts a second importer, never
publishes to production and never deletes originals or failed artifacts.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

BASE = Path('/var/lib/homelab-otel-history/recovery-20261031')
PRODUCER = Path('/home/alchemmist/.local/share/homelab/otel-history-recovery-20261031')
PINNED_THANOS = 'e88cf130a15f91ba8437885231fd3aa27fe88ef118b1fa2f2251465a526c7df9'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(profile='backup-final'):
    global BASE, PRODUCER
    current = profile == 'current-repaired'
    BASE = Path('/var/lib/homelab-otel-history/current-native-finalize-20261031' if current else '/var/lib/homelab-otel-history/recovery-20261031')
    PRODUCER = Path('/var/lib/homelab-otel-history/current-roundtrip-20261031-v2' if current else '/home/alchemmist/.local/share/homelab/otel-history-recovery-20261031')
    expected_samples = 6383043932 if current else 1043291602
    restored_root = Path('/home/alchemmist/otel-history-current-roundtrip-work-20261031/restored') if current else PRODUCER / 'restored'
    native_name = 'otel-history-native-compat-current-replay-20261031' if current else 'otel-history-native-compat-recovered-last-20261031'
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ValueError('Protected native evidence requires root')
    status = {'success': False, 'productionPublished': False, 'startedAtUnix': time.time()}
    try:
        deadline = time.monotonic() + (108000 if current else 43200)
        while not (PRODUCER / 'result.json').exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('Single existing importer did not finish within deadline')
            time.sleep(30)
        imported = json.loads((PRODUCER / 'result.json').read_text())
        if imported.get('success') is not True or imported.get('samples', imported.get('sourceSamples')) != expected_samples:
            raise ValueError('Recovery canonical roundtrip is not complete')
        if current and imported.get('fullCanonicalRoundtripVerified') is not True:
            raise ValueError('Current source needs a complete canonical OTLP roundtrip')
        imported['samples'] = expected_samples
        imported['canonicalSHA256'] = imported.get('canonicalSHA256', imported.get('sourceCanonicalSHA256'))
        expected_digest = '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209' if current else '96b0b9f5f763ec154578de90b490a13683a81f42bae32c634118c8b356189acf'
        if imported['canonicalSHA256'] != expected_digest:
            raise ValueError('Completed roundtrip canonical digest differs from trusted source')
        block = Path(imported['restoredBlock'])
        if block.parent != restored_root or block.is_symlink():
            raise ValueError('Unexpected recovered block location')
        if any(path.is_symlink() for path in block.rglob('*')):
            raise ValueError('Symlinked recovered block rejected')
        stage = BASE / 'stage'
        stage.mkdir(mode=0o700)
        tools = json.loads((BASE / 'tools.json').read_text())
        for name in ['anchors', 'thanos']:
            if sha(BASE / name) != tools[name]:
                raise ValueError('Native validation tool checksum differs')
        if tools['thanos'] != PINNED_THANOS:
            raise ValueError('Native production Thanos pin differs')
        required = sum(path.stat().st_size for path in block.rglob('*') if path.is_file()) * 3
        disk = shutil.disk_usage(BASE)
        if disk.free - required < disk.total // 5:
            raise ValueError('Native finalization would breach 20% disk reserve')
        with (stage / 'candidate.tar').open('xb') as stream, tarfile.open(fileobj=stream, mode='w') as archive:
            archive.add(block, arcname=block.name)
        shutil.copyfile(BASE / 'thanos', stage / 'thanos')
        anchors = json.loads(subprocess.run([str(BASE / 'anchors'), '--block', str(block)], capture_output=True, text=True, check=True, timeout=120).stdout)
        anchors.update(archiveSHA256=sha(stage / 'candidate.tar'), archiveBytes=(stage / 'candidate.tar').stat().st_size,
                       nativeBinarySHA256=PINNED_THANOS)
        native = Path('/var/tmp') / native_name
        native.mkdir(mode=0o700)
        (native / 'request.json').write_text(json.dumps(anchors))
        compatibility = load_module('native_compat', BASE / 'compat.py')
        checked = compatibility.run(native, stage)
        if checked.get('verified') is not True:
            raise ValueError('Actual native Store/Query did not verify')
        destination = Path('/var/lib/homelab-otel-history/staged') / block.name
        destination.mkdir(mode=0o700, parents=True)
        if (native / 'bucket').stat().st_dev != destination.stat().st_dev:
            raise ValueError('Durable native relocation must be same-filesystem')
        inventory = load_module('durable_inventory', BASE / 'durable.py')
        before = inventory.regular_inventory(native / 'bucket')
        os.rename(native / 'bucket', destination / 'bucket')
        if before != inventory.regular_inventory(destination / 'bucket'):
            raise ValueError('Verified native data changed during relocation')
        for name in ['request.json', 'result.json']:
            shutil.copyfile(native / name, destination / name)
        if current:
            shutil.copyfile(PRODUCER / 'result.json', BASE / 'canonical-result.json')
            shutil.copyfile(Path('/var/lib/homelab-otel-history/coverage-20261031/target-integrity.json'), BASE / 'source-integrity.json')
            shutil.copyfile(restored_root.parent / 'otlp/manifest.json', BASE / 'canonical-manifest.json')
        else:
            for name in ['source-inventory.json', 'source-archive-proof.json', 'result.json']:
                shutil.copyfile(PRODUCER / name, BASE / ('canonical-' + name))
        receipt = {'block': block.name, 'durableDirectory': str(destination), 'sameFilesystemRenameVerified': True,
                   'fileCount': len(before), 'fileBytes': sum(value[2] for value in before.values()),
                   'productionPublished': False, 'originalHistoryDeleted': False}
        (destination / 'durability.json').write_text(json.dumps(receipt, indent=2) + '\n')
        (native / 'relocation.json').write_text(json.dumps(receipt, indent=2) + '\n')
        status.update(success=True, samples=imported['samples'], canonicalSHA256=imported['canonicalSHA256'],
                      actualNativeThanosQueryVerified=True, durableStagingVerified=True, restoredBlock=block.name)
    except Exception as error:
        status['errorType'] = type(error).__name__
        raise
    finally:
        status['finishedAtUnix'] = time.time()
        (BASE / 'final-result.json').write_text(json.dumps(status, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=['backup-final', 'current-repaired'], default='backup-final')
    args = parser.parse_args()
    run(args.profile)
