"""Per-node metrics/WAL/compaction storage capacity metadata, never TSDB payloads.

Reads only allowlisted numeric fields of native meta.json, stat/statvfs and
/proc/meminfo. No label values, log bodies, traces, keys, chunks or index reads.
No deletion, retention mutation or acceptance from a short observation window.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time

ROOT = Path('/var/lib/homelab-otel-storage-capacity')
ULID = re.compile(r'[0-9A-HJKMNP-TV-Z]{26}')


def inventory(root, limit=100000):
    if not root.is_dir() or root.is_symlink():
        raise ValueError('Required real storage directory missing or symlinked')
    seen = set()
    allocated = apparent = files = 0
    parts = {'wal': 0, 'chunks_head': 0}
    part_seen = {part: set() for part in parts}
    blocks = []
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if not (Path(directory) / name).is_symlink()]
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            identity = (stat.st_dev, stat.st_ino)
            for part in parts:
                if part in path.relative_to(root).parts and identity not in part_seen[part]:
                    parts[part] += stat.st_blocks * 512
                    part_seen[part].add(identity)
            if identity in seen:
                continue
            seen.add(identity)
            files += 1
            if files > limit:
                raise ValueError('Bounded metadata file budget exceeded')
            allocated += stat.st_blocks * 512
            apparent += stat.st_size
            if name == 'meta.json' and ULID.fullmatch(path.parent.name):
                if stat.st_size > 1024 * 1024:
                    raise ValueError('Native block metadata budget exceeded')
                try:
                    meta = json.loads(path.read_text())
                except FileNotFoundError:
                    continue
                stats = meta['stats']
                selected = {'minTime': meta['minTime'], 'maxTime': meta['maxTime'],
                            'numSamples': stats['numSamples'], 'numSeries': stats['numSeries'],
                            'numChunks': stats['numChunks'], 'resolution': meta.get('thanos', {}).get('downsample', {}).get('resolution', 0)}
                if any(type(value) is not int or value < 0 for value in selected.values()) or selected['maxTime'] <= selected['minTime']:
                    raise ValueError('Invalid native numeric block metadata')
                blocks.append(selected)
    disk = os.statvfs(root)
    return {'files': files, 'allocatedBytes': allocated, 'apparentBytes': apparent,
            'walAndHeadAllocatedBytes': parts, 'nativeBlocks': blocks,
            'device': root.stat().st_dev, 'filesystemTotalBytes': disk.f_blocks * disk.f_frsize,
            'filesystemAvailableBytes': disk.f_bavail * disk.f_frsize, 'payloadsOrLabelsRead': False,
            'concurrentCompactionPossible': True, 'hardlinksDeduplicatedWithinRoot': True}


def run():
    os.umask(0o077)
    config = json.loads((ROOT / 'configuration.json').read_text())
    configuration_sha = hashlib.sha256(Path(__file__).read_bytes() + json.dumps(config, sort_keys=True).encode()).hexdigest()
    observation = {'observedAtUnix': time.time(), 'node': config['node'], 'storage': {}, 'configurationSHA256': configuration_sha,
                   'fullRetentionCapacityAcceptance': False, 'errors': []}
    try:
        for entry in config['paths']:
            path = Path(entry['path'])
            if not path.is_absolute() or not str(path).startswith('/var/lib/') or '..' in path.parts or path == ROOT:
                raise ValueError('Storage path outside explicit /var/lib metadata scope')
            observation['storage'][entry['name']] = inventory(path)
        memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        observation['memory'] = {key: int(memory[key].split()[0]) * 1024 for key in ['MemTotal', 'MemAvailable']}
    except Exception as error:
        observation['errors'].append(type(error).__name__)
    with (ROOT / 'observations.jsonl').open('a') as target:
        target.write(json.dumps(observation) + '\n')
    temporary = ROOT / 'latest.new'
    temporary.write_text(json.dumps(observation, indent=2) + '\n')
    temporary.replace(ROOT / 'latest.json')
    print(json.dumps(observation))
    if observation['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    run()
