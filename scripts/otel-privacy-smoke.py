import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request


def isolated_config(source, output):
    document = json.loads(json.dumps(source))
    receiver = document['receivers']['otlp']['protocols']['http']
    receiver['endpoint'] = '127.0.0.1:14318'
    document['receivers'] = {'otlp': {'protocols': {'http': receiver}}}
    document['processors'] = {name: document['processors'][name] for name in document['service']['pipelines']['logs']['processors']}
    document['exporters'] = {'file': {'path': str(output), 'flush_interval': '100ms'}}
    document['extensions'] = {'file_storage': document['extensions']['file_storage']}
    document['service']['extensions'] = ['file_storage']
    document['service']['pipelines'] = {'logs': {
        'receivers': ['otlp'], 'processors': source['service']['pipelines']['logs']['processors'], 'exporters': ['file']}}
    return document


def send(context, payload):
    request = urllib.request.Request('https://127.0.0.1:14318/v1/logs',
                                     data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, context=context, timeout=10) as response:
        result = json.load(response)
    if int(result.get('partialSuccess', {}).get('rejectedLogRecords', 0)):
        raise ValueError('Synthetic logs were rejected')


def run(binary, config, tls, workspace):
    if os.readlink('/proc/self/ns/net') == os.readlink('/proc/1/ns/net'):
        raise ValueError('A separate network namespace is mandatory')
    workspace.mkdir(mode=0o700, exist_ok=False)
    output = workspace / 'sanitized.json'
    prepared = isolated_config(json.loads(config.read_text()), output)
    (workspace / 'config.json').write_text(json.dumps(prepared))
    now = time.time_ns()
    environment = {**os.environ, 'OTEL_TLS_DIR': str(tls), 'OTEL_STORAGE_DIR': str(workspace / 'storage'),
                   'OTEL_BIND_IP': '127.0.0.1', 'OTEL_LOG_INGESTION_START_NS': str(now - 1000000000)}
    context = ssl.create_default_context(cafile=str(tls / 'ca.crt'))
    context.load_cert_chain(str(tls / 'client.crt'), str(tls / 'client.key'))
    records = [
        {'timeUnixNano': str(now - 2000000000), 'body': {'stringValue': 'HISTORICAL_DO_NOT_IMPORT'}},
        {'timeUnixNano': '0', 'body': {'stringValue': 'UNKNOWN_TIMESTAMP_DO_NOT_IMPORT'}},
        {'timeUnixNano': str(now), 'body': {'stringValue': 'plain-sentinel password=FIXTURE_PASSWORD token=FIXTURE_TOKEN Bearer FIXTURE_BEARER alice@example.invalid'}},
        {'timeUnixNano': str(now), 'body': {'kvlistValue': {'values': [
            {'key': 'password', 'value': {'stringValue': 'FIXTURE_MAP_SECRET'}},
            {'key': 'text', 'value': {'stringValue': 'structured-sentinel'}}]}}},
        {'timeUnixNano': str(now), 'body': {'stringValue': '{"password":"FIXTURE_JSON_SECRET","text":"json-sentinel"}'},
         'attributes': [{'key': 'authorization', 'value': {'stringValue': 'FIXTURE_ATTRIBUTE_SECRET'}}]},
    ]
    payload = {'resourceLogs': [{'resource': {'attributes': [
        {'key': 'service.name', 'value': {'stringValue': 'synthetic-privacy-smoke'}},
        {'key': 'secret', 'value': {'stringValue': 'FIXTURE_RESOURCE_SECRET'}}]},
        'scopeLogs': [{'logRecords': records}]}]}
    log = (workspace / 'collector.log').open('x')
    process = subprocess.Popen([str(binary), '--config=' + str(workspace / 'config.json')],
                               env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 30
        while True:
            if process.poll() is not None:
                raise RuntimeError('Collector stopped; inspect the private smoke workspace')
            try:
                with socket.create_connection(('127.0.0.1', 14318), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Synthetic receiver startup timed out')
                time.sleep(0.1)
        send(context, payload)
        anonymous = ssl.create_default_context(cafile=str(tls / 'ca.crt'))
        try:
            send(anonymous, payload)
        except urllib.error.URLError as error:
            if not isinstance(error.reason, (ssl.SSLError, ConnectionResetError, BrokenPipeError)):
                raise
        except (ssl.SSLError, ConnectionResetError, BrokenPipeError):
            pass
        else:
            raise ValueError('Receiver accepted a request without a client certificate')
        while True:
            text = output.read_text() if output.exists() else ''
            if all(sentinel in text for sentinel in ['plain-sentinel', 'structured-sentinel', 'json-sentinel']):
                break
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('Expected sanitized fixture records were not exported')
            time.sleep(0.1)
        forbidden = ['FIXTURE_PASSWORD', 'FIXTURE_TOKEN', 'FIXTURE_BEARER', 'alice@example.invalid',
                     'FIXTURE_MAP_SECRET', 'FIXTURE_JSON_SECRET', 'FIXTURE_ATTRIBUTE_SECRET',
                     'FIXTURE_RESOURCE_SECRET', 'HISTORICAL_DO_NOT_IMPORT', 'UNKNOWN_TIMESTAMP_DO_NOT_IMPORT']
        if any(value in text for value in forbidden):
            raise ValueError('Privacy or historical-cut fixture leaked into synthetic output')
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
    result = {'schemaVersion': 1, 'observedAt': datetime.now(timezone.utc).isoformat(),
              'syntheticSourcesOnly': True, 'separateNetworkNamespace': True, 'productionModified': False,
              'mTLSMissingClientRejected': True, 'historicalCutVerified': True, 'zeroTimestampRejected': True,
              'textAndStructuredPrivacyFixturesVerified': True, 'allSourcePrivacyVerified': False,
              'productionDeployed': False}
    (workspace / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser()
    for name in ['binary', 'config', 'tls', 'workspace']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(run(args.binary, args.config, args.tls, args.workspace), indent=2))


if __name__ == '__main__':
    main()
