#!/usr/bin/env python3
"""Isolated pinned-Collector privacy/severity and persistent full-queue recovery probe.
Only synthetic data; prints counts/IDs, never Collector logs or payloads. Requires Docker and PyYAML.
"""
import concurrent.futures as futures
import json
import pathlib
import subprocess
import tempfile
import time
import urllib.request
import uuid
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = json.loads((ROOT / 'deploy/monitoring/otel-images.lock.json').read_text())['images']['collector']['image']
TAG = 'log-test-' + uuid.uuid4().hex[:8]
NAMES = []

def docker(*args, check=True):
    return subprocess.run(['docker', *args], check=check, capture_output=True)

def launch(name, config, network=None, publish=False):
    NAMES.append(name)
    args = ['create', '--user', '0', '--name', name]
    if network:
        args += ['--network', network]
    if publish:
        args += ['-p', '127.0.0.1::4318']
    docker(*args, IMAGE, '--config=/tmp/config.json')
    with tempfile.NamedTemporaryFile(mode='w') as f:
        json.dump(config, f); f.flush()
        docker('cp', f.name, name + ':/tmp/config.json')
    docker('start', name)
    time.sleep(2)
    assert docker('inspect', '-f', '{{.State.Running}}', name).stdout.strip() == b'true', 'Collector failed startup (logs deliberately withheld)'
    if publish:
        port = docker('port', name, '4318/tcp').stdout.decode().strip().split(':')[-1]
        return 'http://127.0.0.1:' + port + '/v1/logs'

def config(processors, exporter):
    return {'receivers': {'otlp': {'protocols': {'http': {'endpoint': '0.0.0.0:4318'}}}},
            'processors': processors, 'exporters': exporter,
            'service': {'pipelines': {'logs': {'receivers': ['otlp'], 'processors': list(processors), 'exporters': list(exporter)}}}}

def value(v):
    if isinstance(v, dict):
        return {'kvlistValue': {'values': [{'key': k, 'value': value(x)} for k, x in v.items()]}}
    if isinstance(v, list):
        return {'arrayValue': {'values': [value(x) for x in v]}}
    return {'stringValue': str(v)}

def send(url, ident, body):
    payload = {'resourceLogs': [{'scopeLogs': [{'logRecords': [{'body': value(body), 'attributes': [{'key': 'test.id', 'value': value(ident)}, {'key': 'nested', 'value': value({'headers': {'x-custom': 'PRIVATE_SENTINEL'}, 'prompt': 'PRIVATE_SENTINEL', 'status': 'safe-attribute'})}]}]}]}]}
    req = urllib.request.Request(url, json.dumps(payload).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=2) as response:
        assert response.status == 200

def output(name):
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / 'out'
        docker('cp', name + ':/tmp/output.json', str(path))
        return [r for line in path.read_text().splitlines() for resource in json.loads(line)['resourceLogs'] for scope in resource['scopeLogs'] for r in scope['logRecords']]

def ids(records):
    return {a['value']['stringValue'] for r in records for a in r.get('attributes', []) if a['key'] == 'test.id'}

def main():
    agent = yaml.safe_load((ROOT / 'deploy/monitoring/otel/agent.yaml').read_text())
    cluster = yaml.safe_load((ROOT / 'deploy/monitoring/otel/cluster-logs-candidate.yaml').read_text())
    active = yaml.safe_load((ROOT / 'deploy/monitoring/otel/cluster.yaml').read_text())
    assert active['processors']['transform/log-privacy'] == cluster['processors']['transform/log-privacy'], 'promoted privacy differs from tested candidate'
    assert active['service']['pipelines']['logs'] == cluster['service']['pipelines']['logs'], 'promoted logs pipeline differs from tested candidate'
    assert 'batch/logs' not in cluster['service']['pipelines']['logs']['processors']
    assert cluster['exporters']['otlp_http/loki']['sending_queue']['block_on_overflow']
    for source, source_config in [('agent', agent), ('cluster', cluster)]:
        processors = {k: source_config['processors'][k] for k in (['transform/log-identity'] if source == 'agent' else []) + ['transform/log-privacy']}
        name = TAG + '-' + source
        url = launch(name, config(processors, {'file': {'path': '/tmp/output.json'}}), publish=True)
        for level in ['INFO', 'WARN', 'ERROR']:
            send(url, level, level + ' synthetic healthy operation')
        sensitive = {'event': 'safe-event', 'nested': {'prompt': 'PRIVATE_SENTINEL', 'headers': {'x-custom': 'PRIVATE_SENTINEL'}, 'request': {'body': 'PRIVATE_SENTINEL'}, 'response.body': 'PRIVATE_SENTINEL', 'ok': 'safe-value'}, 'items': [{'completion': 'PRIVATE_SENTINEL', 'status': 'safe-status'}]}
        send(url, 'invalid-json', '{\"prompt\":\"PRIVATE_SENTINEL')
        send(url, 'map', sensitive)
        send(url, 'json', json.dumps(sensitive))
        send(url, 'json-array', json.dumps([sensitive]))
        send(url, 'array', [sensitive])
        send(url, 'freeform', 'INFO request.body: PRIVATE_SENTINEL\nPRIVATE_SENTINEL')
        time.sleep(1); docker('stop', '-t', '3', name)
        records = output(name)
        assert len(records) == 9
        encoded = json.dumps(records)
        assert 'PRIVATE_SENTINEL' not in encoded
        assert encoded.count('safe-event') == 2 and encoded.count('safe-value') == 2
        if source == 'agent':
            actual = {next(a['value']['stringValue'] for a in r['attributes'] if a['key'] == 'test.id'): r['severityText'] for r in records}
            assert all(actual[level] == level.lower() for level in ['INFO', 'WARN', 'ERROR'])
        print(source + ': privacy=9/9; severity=' + ('3/3' if source == 'agent' else 'agent-owned'))
    network = TAG + '-net'
    docker('network', 'create', '--internal', network)
    try:
        sink = TAG + '-sink'; sender = TAG + '-sender'
        q = dict(cluster['exporters']['otlp_http/loki']['sending_queue'])
        q.update(sizer='requests', queue_size=2, num_consumers=1)
        exporter = {'otlp_http': {'endpoint': 'http://' + sink + ':4318', 'sending_queue': q, 'retry_on_failure': {'enabled': True, 'initial_interval': '1s', 'max_interval': '1s', 'max_elapsed_time': '0s'}, 'timeout': '1s'}}
        cfg = config({'transform/log-privacy': cluster['processors']['transform/log-privacy']}, exporter)
        cfg['extensions'] = {'file_storage': {'directory': '/tmp/queue', 'create_directory': True, 'fsync': True}}
        cfg['service']['extensions'] = ['file_storage']
        url = launch(sender, cfg, network, publish=True)
        def retry(i):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    send(url, str(i), 'INFO recovery-id-' + str(i)); return i
                except Exception:
                    time.sleep(.2)
            raise AssertionError('request retry deadline')
        with futures.ThreadPoolExecutor(max_workers=12) as pool:
            pending = [pool.submit(retry, i) for i in range(12)]
            time.sleep(4)
            acknowledged = sum(f.done() for f in pending)
            assert 0 < acknowledged < 12, 'queue did not exert backpressure'
            print('outage: sent=12 acknowledged=' + str(acknowledged) + ' blocked=' + str(12-acknowledged))
            docker('kill', sender)
            docker('start', sender)
            launch(sink, config({}, {'file': {'path': '/tmp/output.json'}}), network)
            assert len([f.result() for f in pending]) == 12
        time.sleep(5)
        docker('stop', '-t', '3', sender); docker('stop', '-t', '3', sink)
        records = output(sink)
        recovered = ids(records)
        assert recovered == {str(i) for i in range(12)}, 'missing recovery IDs'
        print('restart recovery: unique=12/12 total=' + str(len(records)) + ' IDs=' + ','.join(sorted(recovered, key=int)))
    finally:
        for name in NAMES:
            docker('rm', '-f', name, check=False)
        docker('network', 'rm', network, check=False)

if __name__ == '__main__':
    try:
        main()
    finally:
        for name in NAMES:
            docker('rm', '-f', name, check=False)
