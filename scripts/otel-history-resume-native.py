"""Complete a verified native relocation after missing staging-parent failure.

Reuses the completed canonical/native checks; preserves both failed receipts.
Never reruns an importer, publishes data, or deletes original history.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import time

ROOT = Path('/var/lib/homelab-otel-history')
FINAL = ROOT / 'current-native-finalize-20261031'
NATIVE = Path('/var/tmp/otel-history-native-compat-current-replay-20261031')
TAIL = ROOT / 'tail-roundtrip-20261101'
WORK = Path('/home/alchemmist/otel-history-current-roundtrip-work-20261031')
SHA = '0904e594038c9cfc60720e01bee3b27cbfdca450b913dd9f5f5dda8da16c4209'
PIN = 'e88cf130a15f91ba8437885231fd3aa27fe88ef118b1fa2f2251465a526c7df9'


def validate(imported, checked, manifest, failed, tail, progress):
    if not (imported.get('success') is True and imported.get('fullCanonicalRoundtripVerified') is True
            and imported['sourceSamples'] == 6383043932 and imported['sourceCanonicalSHA256'] == SHA
            and checked.get('verified') is True and checked.get('nativeBinarySHA256') == PIN
            and checked.get('nativeIndexIssueVerificationPassed') is True and checked.get('archiveSHA256Verified') is True
            and checked['block'] == Path(imported['restoredBlock']).name
            and manifest['samples'] == 6383043932 and manifest['canonicalSHA256'] == SHA
            and failed.get('success') is False and failed.get('errorType') == 'FileNotFoundError'
            and tail.get('success') is False and tail.get('blocks') == []
            and progress.get('phase') == 'await-current-native-and-six-original-comparisons'):
        raise ValueError('Only completed native checks and untouched prerequisite-wait queue may resume')


def run():
    os.umask(0o077)
    if os.geteuid() != 0 or socket.gethostname() != 'socrat-0':
        raise ValueError('Explicit protected trusted-host native completion only')
    read = lambda path: json.loads(path.read_text())
    with (ROOT / 'importer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        imported = read(ROOT / 'current-roundtrip-20261031-v2/result.json')
        checked, manifest = read(NATIVE / 'result.json'), read(WORK / 'otlp/manifest.json')
        validate(imported, checked, manifest, read(FINAL / 'final-result.json'), read(TAIL / 'result.json'), read(TAIL / 'progress.json'))
        destination = ROOT / 'staged' / checked['block']
        if destination.exists() or NATIVE.is_symlink() or (NATIVE / 'bucket').is_symlink():
            raise ValueError('Existing destination or symlink requires inspection')
        spec = importlib.util.spec_from_file_location('durable', FINAL / 'durable.py')
        durable = importlib.util.module_from_spec(spec); spec.loader.exec_module(durable)
        before = durable.regular_inventory(NATIVE / 'bucket')
        if not before or not (NATIVE / 'bucket' / checked['block'] / 'meta.json').is_file():
            raise ValueError('Verified native bucket is absent')
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.mkdir(mode=0o700)
        if (NATIVE / 'bucket').stat().st_dev != destination.stat().st_dev:
            raise ValueError('Only same-filesystem native rename allowed')
        os.rename(NATIVE / 'bucket', destination / 'bucket')
        if before != durable.regular_inventory(destination / 'bucket'):
            raise ValueError('Native inventory changed during rename')
        for name in ['request.json', 'result.json']:shutil.copyfile(NATIVE / name, destination / name)
        receipt = {'block': checked['block'], 'durableDirectory': str(destination), 'sameFilesystemRenameVerified': True,
            'fileCount': len(before), 'fileBytes': sum(x[2] for x in before.values()), 'productionPublished': False, 'originalHistoryDeleted': False}
        (destination / 'durability.json').write_text(json.dumps(receipt, indent=2))
        (NATIVE / 'relocation.json').write_text(json.dumps(receipt, indent=2))
        for source, name in [(ROOT / 'current-roundtrip-20261031-v2/result.json', 'canonical-result.json'),
                (ROOT / 'coverage-20261031/target-integrity.json', 'source-integrity.json'), (WORK / 'otlp/manifest.json', 'canonical-manifest.json')]:
            shutil.copyfile(source, FINAL / name)
        suffix = str(time.time_ns())
        (FINAL / 'final-result.json').rename(FINAL / ('final-result.failed-' + suffix + '.json'))
        status = {'success': True, 'samples': 6383043932, 'canonicalSHA256': SHA, 'actualNativeThanosQueryVerified': True,
            'durableStagingVerified': True, 'restoredBlock': checked['block'], 'productionPublished': False,
            'resumedAlreadyVerifiedNativeRelocation': True, 'finishedAtUnix': time.time()}
        temporary = FINAL / 'final-result.resumed.tmp'; temporary.write_text(json.dumps(status, indent=2)); temporary.replace(FINAL / 'final-result.json')
        (TAIL / 'result.json').rename(TAIL / ('result.prerequisite-failed-' + suffix + '.json'))
        print(json.dumps(status))


if __name__ == '__main__':run()
