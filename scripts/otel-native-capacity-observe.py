"""Bounded metadata/counter-only native log/trace capacity observations.

No log bodies, trace payloads, metrics labels, credential values or historical
TSDB data are recorded. Observations are inputs, NOT retention acceptance.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import ssl
import time
import urllib.request

ROOT = Path('/var/lib/homelab-otel-capacity')
PATHS = {'loki': Path('/var/lib/homelab-otel-loki'), 'tempo': Path('/var/lib/homelab-otel-tempo'),
         'applicationIngressQueue': Path('/var/lib/homelab-otel/application-ingress-queue')}
METRICS = {'process_start_time_seconds', 'process_resident_memory_bytes', 'process_cpu_seconds_total',
           'loki_distributor_bytes_received_total', 'loki_distributor_lines_received_total',
           'loki_distributor_ingester_appends_total', 'tempo_distributor_bytes_received_total',
           'tempo_distributor_spans_received_total', 'otelcol_exporter_sent_spans_total',
           'otelcol_exporter_enqueue_failed_spans_total', 'otelcol_exporter_send_failed_spans_total',
           'otelcol_exporter_queue_size', 'otelcol_exporter_queue_capacity'}


def counters(text):
    result = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{.*\})?\s+([^\s]+)(?:\s+[^\s]+)?', line)
        if match and match[1] in METRICS:
            value = float(match[2])
            if not math.isfinite(value) or value < 0:
                raise ValueError('Invalid native capacity counter')
            result[match[1]] = result.get(match[1], 0) + value
    return result


def footprint(root):
    if not root.is_dir():
        raise ValueError('Required native storage root is missing')
    seen = set()
    apparent = allocated = files = 0
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if not (Path(directory) / name).is_symlink()]
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue  # Native compaction may remove files during read-only inventory.
            identity = (stat.st_dev, stat.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            files += 1
            if files > 100000:
                raise ValueError('Native metadata walk exceeded bounded file budget')
            apparent += stat.st_size
            allocated += stat.st_blocks * 512
    return {'files': files, 'apparentBytes': apparent, 'allocatedBytes': allocated,
            'metadataOnly': True, 'concurrentCompactionPossible': True}


def configuration_sha256():
    digest = hashlib.sha256(Path(__file__).read_bytes())
    for path in ['/etc/homelab-otel/loki.yaml', '/etc/homelab-otel/tempo.yaml', '/etc/homelab-otel/application-ingress.yaml', '/var/lib/homelab-otel-soak/configuration-epoch.json']:
        digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def run():
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, exist_ok=True)
    observation = {'observedAtUnix': time.time(), 'fullRetentionCapacityAcceptance': False,
                   'metricsHistoryCapacityIncluded': False, 'errors': []}
    try:
        observation['configurationSHA256'] = configuration_sha256()
        observation['storage'] = {name: footprint(path) for name, path in PATHS.items()}
        disk = os.statvfs(ROOT)
        observation['filesystem'] = {'totalBytes': disk.f_blocks * disk.f_frsize, 'availableBytes': disk.f_bavail * disk.f_frsize}
        memory = {key: int(value.split()[0]) * 1024 for key, value in (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())}
        observation['memory'] = {'totalBytes': memory['MemTotal'], 'availableBytes': memory['MemAvailable']}
        tls = Path('/var/lib/homelab-otel/tls')
        context = ssl.create_default_context(cafile=str(tls / 'ca.crt'))
        context.load_cert_chain(str(tls / 'client.crt'), str(tls / 'client.key'))
        observation['nativeCounters'] = {}
        for name, url, secure in [('loki', 'https://10.250.0.3:3100/metrics', True),
                                  ('tempo', 'https://10.250.0.3:3200/metrics', True),
                                  ('applicationIngress', 'http://127.0.0.1:18889/metrics', False)]:
            with urllib.request.urlopen(url, context=context if secure else None, timeout=4) as response:
                body = response.read(8 * 1024**2 + 1)
            if len(body) > 8 * 1024**2:
                raise ValueError('Native capacity metric inspection budget exceeded')
            selected = counters(body.decode())
            if not selected:
                raise ValueError('No known native capacity counters were observed')
            observation['nativeCounters'][name] = selected
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
