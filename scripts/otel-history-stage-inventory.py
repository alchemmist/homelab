"""Rebuild full canonical/CRC receipts of six immutable native-validated stages.

Read-only. Matching these fresh hashes to original-source corpus receipts is a
separate mandatory gate; native anchors alone never replace that comparison.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

BASE = Path('/var/lib/homelab-otel-history/stage-inventory-20261031')
COUNTS = (235173517, 4606695568, 5955368159, 6137437488, 260844250, 261337432)
BINARY_SHA = '9725e698476cbd4ab38f04c3481083067574fd580c479afdc57bfd4c3f8bab63'
SNAPSHOT_SHA = '7f7fac361193bea3f23f53bcdb40ceeef2495f724e3d0d86ecbc486fd371088f'


def save(name, document):
    temp = BASE / (name + '.tmp')
    temp.write_text(json.dumps(document, indent=2) + '\n')
    temp.replace(BASE / name)


def run():
    os.umask(0o077)
    if os.geteuid() != 0 or (BASE / 'result.json').exists():
        raise ValueError('New protected stage verification required')
    report = {'success': False, 'productionModified': False, 'sourceGoldenHashComparisonStillRequired': True, 'blocks': []}
    try:
        binary = BASE / 'otel-history'
        with binary.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != BINARY_SHA:
                raise ValueError('Canonical inventory executable checksum mismatch')
        for expected in COUNTS:
            candidates = []
            for path in Path('/var/lib/homelab-otel-history/staged').glob('*/bucket/*/meta.json'):
                meta = json.loads(path.read_text())
                if meta['stats']['numSamples'] == expected:
                    validated = json.loads((path.parents[2] / 'result.json').read_text())
                    if validated.get('verified') is True:
                        candidates.append((path.parent, meta))
            if len(candidates) != 1:
                raise ValueError('Exactly one protected native stage expected for this source count')
            block, meta = candidates[0]
            save('progress.json', dict(report, phase='complete-canonical-stage-inventory', block=block.name))
            with (BASE / (block.name + '.stderr')).open('x') as errors, (BASE / (block.name + '.json')).open('x') as output:
                subprocess.run([str(binary), 'inventory', '--source', str(block)], stdout=output, stderr=errors, check=True,
                               timeout=7200, env=dict(os.environ, GOMAXPROCS='1', GOMEMLIMIT='256MiB'))
            inventory = json.loads((BASE / (block.name + '.json')).read_text())
            if inventory['samples'] != expected or (expected == COUNTS[0] and inventory['canonicalSHA256'] != SNAPSHOT_SHA):
                raise ValueError('Protected stage source count or known snapshot hash differs')
            report['blocks'].append({'block': block.name, 'samples': expected, 'canonicalSHA256': inventory['canonicalSHA256'],
                                     'externalLabels': meta.get('thanos', {}).get('labels', {}), 'minTime': meta['minTime'], 'maxTime': meta['maxTime']})
            save('canonical-progress.json', report)
        report.update(success=True, samples=sum(COUNTS))
    except Exception as error:
        report['errorType'] = type(error).__name__
        raise
    finally:
        save('result.json', report)


if __name__ == '__main__':
    run()
