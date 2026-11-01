"""Create a private, fresh, content-pinned request for the native host metrics canary."""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NODES = ('socrat-0', 'socrat-1', 'socrat-2', 'socrat-3')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pinned_binary(directory, key, filename, images):
    receipt = json.loads((directory / 'receipt.json').read_text())
    entry = receipt['binaries'][key]
    binary = directory / filename
    if receipt.get('architecture') != 'linux/amd64' or entry['image'] != images[key]['image'] or digest(binary) != entry['sha256']:
        raise ValueError('Canary binary differs from verified receipt or repository image lock')
    return entry['sha256']


def create(bundle, binaries, prometheus, exporter_path, backend_ip):
    if ipaddress.ip_address(backend_ip) not in ipaddress.ip_network('10.250.0.0/24'):
        raise ValueError('Backend must use an existing private WireGuard address')
    if not str(exporter_path).startswith('/var/tmp/otel-host-source-canary-') or '..' in exporter_path.parts:
        raise ValueError('Explicit already verified native source executable path required')
    contract = json.loads((bundle / 'contract.json').read_text())
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(contract['collectedAt'])).total_seconds()
    if not 0 <= age <= 900:
        raise ValueError('Fresh complete scrape contract required')
    labels, hashes = {}, {}
    for node in NODES:
        document = yaml.safe_load((bundle / (node + '.yaml')).read_text())
        actual = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if actual != contract['outputSHA256'][node]:
            raise ValueError('Native source document differs from compiled contract')
        jobs = document['scrape_configs']
        if len(jobs) != 1 or len(jobs[0]['static_configs']) != 1 or jobs[0]['static_configs'][0]['targets'] != ['127.0.0.1:19100']:
            raise ValueError('Exactly one independent loopback host source is required')
        labels[node] = jobs[0]['static_configs'][0]['labels']
        hashes[node] = actual
    images = json.loads((ROOT / 'deploy/monitoring/otel-images.lock.json').read_text())['images']
    exporter = json.loads((ROOT / 'deploy/monitoring/otel-node-exporter.lock.json').read_text())
    return {'backendIP': backend_ip,
            'collectorSHA256': pinned_binary(binaries, 'collector', 'otelcol-contrib', images),
            'prometheusSHA256': pinned_binary(prometheus, 'validationPrometheus', 'prometheus', images),
            'exporterPath': str(exporter_path), 'exporterSHA256': exporter['binarySHA256'],
            'expectedLabels': labels, 'hostScrapeSHA256': hashes,
            'scrapeContractCollectedAt': contract['collectedAt'], 'sourceYAMLTextSHA256': contract['sourceYAMLTextSHA256'],
            'minimumAvailableMemoryBytes': {'socrat-0': 832 * 2**20, 'socrat-1': 2368 * 2**20,
                                           'socrat-2': 576 * 2**20, 'socrat-3': 576 * 2**20},
            'productionIngestionChanged': False}


def main():
    parser = argparse.ArgumentParser()
    for name in ('bundle', 'binaries', 'prometheus', 'exporter-path', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--backend-ip', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    result = create(args.bundle, args.binaries, args.prometheus, args.exporter_path, args.backend_ip)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'requestCreated': True, 'hostCount': 4, 'productionIngestionChanged': False}))


if __name__ == '__main__':
    main()
