import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


SERVICE = 'otel-isolated-signal-smoke'
SECRET = 'synthetic-sensitive-value'


def request(context, port, path, document=None):
    data = json.dumps(document).encode() if document is not None else None
    req = urllib.request.Request('https://127.0.0.1:' + str(port) + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, context=context, timeout=10) as response:
        body = response.read()
    return json.loads(body) if body else {}


def attribute(key, value):
    return {'key': key, 'value': {'stringValue': value}}


def trace_fixtures(now):
    spans = []
    groups = {}
    for category, count in [('error', 8), ('http5xx', 8), ('legacy5xx', 8), ('slow', 8), ('normal', 200)]:
        groups[category] = set()
        for index in range(count):
            identity = hashlib.sha256((category + '-' + str(index)).encode()).hexdigest()
            groups[category].add(identity[:32])
            attrs = [attribute('authorization', SECRET), attribute('gen_ai.input.messages', SECRET),
                     attribute('url.full', 'https://fixture.invalid/path?token=' + SECRET)]
            if category in ('http5xx', 'legacy5xx'):
                key = 'http.response.status_code' if category == 'http5xx' else 'http.status_code'
                attrs.append({'key': key, 'value': {'intValue': '503'}})
            spans.append({'traceId': identity[:32], 'spanId': identity[32:48], 'name': 'synthetic-' + category,
                'kind': 2, 'startTimeUnixNano': str(now - (3_000_000_000 if category == 'slow' else 100_000_000)),
                'endTimeUnixNano': str(now), 'attributes': attrs, 'status': {'code': 2 if category == 'error' else 1, 'message': SECRET},
                'events': [{'timeUnixNano': str(now), 'name': 'synthetic-event', 'attributes': [attribute('password', SECRET)]}]})
    body = {'resourceSpans': [{'resource': {'attributes': [attribute('service.name', SERVICE), attribute('token', SECRET)]},
        'scopeSpans': [{'scope': {'name': 'homelab.synthetic.acceptance'}, 'spans': spans}]}]}
    return body, groups


def logs_fixture(now):
    return {'resourceLogs': [{'resource': {'attributes': [attribute('service.name', SERVICE), attribute('authorization', SECRET)]},
        'scopeLogs': [{'scope': {'name': 'homelab.synthetic.acceptance'}, 'logRecords': [
            {'timeUnixNano': str(now), 'body': {'stringValue': 'fresh-fixture password=' + SECRET}, 'attributes': [attribute('token', SECRET)]},
            {'timeUnixNano': '0', 'body': {'stringValue': 'forbidden-time-zero'}},
            {'timeUnixNano': str(now - 3600 * 10**9), 'body': {'stringValue': 'forbidden-history'}}]}]}]}


def run(args):
    if os.readlink('/proc/self/ns/net') == os.readlink('/proc/1/ns/net'):
        raise ValueError('Signal smoke requires an isolated loopback-only network namespace')
    args.workspace.mkdir(mode=0o700, exist_ok=False)
    configs = {name: json.loads((args.config / (name + '.json')).read_text()) for name in ['cluster', 'trace-gateway', 'loki', 'tempo']}
    cluster = configs['cluster']
    cluster['receivers'] = {'otlp': {'protocols': {'http': cluster['receivers']['otlp']['protocols']['http']}}}
    cluster['service']['pipelines'].pop('metrics')
    cluster['service']['telemetry'] = {'metrics': {'level': 'none'}}
    cluster['extensions'].pop('health_check')
    cluster['service']['extensions'] = ['file_storage']
    cluster['exporters'].pop('otlp_http/metrics')
    cluster['receivers']['otlp']['protocols']['http']['endpoint'] = '127.0.0.1:4318'
    gateway = configs['trace-gateway']
    gateway['receivers']['otlp']['protocols']['grpc']['endpoint'] = '127.0.0.1:14317'
    gateway['service']['telemetry'] = {'metrics': {'level': 'none'}}
    configs['tempo']['distributor']['receivers']['otlp']['protocols']['grpc']['endpoint'] = '127.0.0.1:24317'
    configs['tempo']['memberlist']['advertise_addr'] = '127.0.0.1'
    boundary = time.time_ns() - 1_000_000_000
    environment = {**os.environ, 'OTEL_BIND_IP': '127.0.0.1', 'OTEL_TLS_DIR': str(args.tls),
        'OTEL_STORAGE_DIR': str(args.workspace / 'state'), 'OTEL_LOG_INGESTION_START_NS': str(boundary),
        'OTEL_LOKI_ENDPOINT': 'https://127.0.0.1:3100/otlp', 'OTEL_TRACE_GATEWAY_ENDPOINT': '127.0.0.1:14317',
        'OTEL_TEMPO_ENDPOINT': '127.0.0.1:24317'}
    children = []
    logs = []
    context = ssl.create_default_context(cafile=str(args.tls / 'ca.crt'))
    context.load_cert_chain(str(args.tls / 'client.crt'), str(args.tls / 'client.key'))
    try:
        for name in ['loki', 'tempo', 'trace-gateway', 'cluster']:
            path = args.workspace / (name + '.json')
            path.write_text(json.dumps(configs[name]))
            if name in ('cluster', 'trace-gateway'):
                command = [str(args.binaries / 'otelcol-contrib'), '--config=' + str(path)]
            else:
                command = [str(args.binaries / name), '-config.file=' + str(path), '-config.expand-env=true']
            log = (args.workspace / (name + '.log')).open('x')
            logs.append(log)
            children.append(subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT))
        started = time.monotonic()
        deadline = started + 80
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('Native signal component stopped; inspect private run logs')
            try:
                for port in [3100, 3200]:
                    with urllib.request.urlopen('https://127.0.0.1:' + str(port) + '/ready', context=context, timeout=3) as response:
                        if response.status != 200:
                            raise ValueError('Backend not ready')
                break
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise RuntimeError('Native signal backend readiness timed out')
                time.sleep(1)
        now = time.time_ns()
        traces, groups = trace_fixtures(now)
        request(context, 4318, '/v1/logs', logs_fixture(now))
        request(context, 4318, '/v1/traces', traces)
        selector = urllib.parse.urlencode({'query': '{service_name="' + SERVICE + '"}', 'start': str(boundary), 'end': str(now + 300 * 10**9), 'limit': 100})
        search = urllib.parse.urlencode({'tags': 'service.name=' + SERVICE, 'limit': 1000,
            'start': str(now // 10**9 - 60), 'end': str(now // 10**9 + 300)})
        deadline = time.monotonic() + 90
        ids = set()
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('Native signal component stopped during delivery')
            loki = request(context, 3100, '/loki/api/v1/query_range?' + selector)
            data = request(context, 3200, '/api/search?' + search)
            ids = {trace['traceID'].lower().zfill(32) for trace in data.get('traces', [])}
            mandatory = set.union(*(groups[key] for key in ['error', 'http5xx', 'legacy5xx', 'slow']))
            if loki.get('data', {}).get('result') and mandatory <= ids:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Native log delivery or mandatory tail sampling timed out')
            time.sleep(2)
        serialized = json.dumps(loki)
        if SECRET in serialized or 'forbidden-history' in serialized or 'forbidden-time-zero' in serialized or 'fresh-fixture' not in serialized:
            raise ValueError('Loki privacy or historical boundary failed')
        normal = len(groups['normal'] & ids)
        if not 5 <= normal <= 45:
            raise ValueError('Normal trace sampling is outside the synthetic acceptance range')
        for identity in sorted(mandatory):
            body = request(context, 3200, '/api/traces/' + identity)
            if SECRET in json.dumps(body):
                raise ValueError('Trace attribute/event/resource privacy failed')
        unauthenticated = ssl.create_default_context(cafile=str(args.tls / 'ca.crt'))
        for port in [3100, 3200]:
            try:
                with urllib.request.urlopen('https://127.0.0.1:' + str(port) + '/ready', context=unauthenticated, timeout=5):
                    pass
            except (ssl.SSLError, ConnectionResetError):
                continue
            except urllib.error.URLError as error:
                if isinstance(error.reason, ssl.SSLError):
                    continue
                raise
            raise ValueError('Backend unexpectedly accepted a client without a certificate')
        result = {'schemaVersion': 1, 'observedAt': datetime.now(timezone.utc).isoformat(),
            'productionModified': False, 'productionDeployed': False, 'syntheticFixturesOnly': True,
            'separateNetworkNamespace': True, 'nativeLokiOTLPDeliveryVerified': True,
            'nativeTempoOTLPDeliveryVerified': True, 'logPrivacyAndBoundaryVerified': True,
            'traceAttributeEventResourcePrivacyVerified': True, 'backendClientCertificateRequired': True,
            'mandatoryTraceCount': len(mandatory), 'mandatoryTracesRetained': len(mandatory & ids),
            'normalTraceCount': len(groups['normal']), 'normalTracesRetained': normal,
            'tailDecisionWaitSeconds': 30, 'elapsedSeconds': round(time.monotonic() - started, 3),
            'productionTraceRateAndRetentionCapacityVerified': False, 'readyForCutover': False}
        (args.workspace / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for log in logs:
            log.close()


def main():
    parser = argparse.ArgumentParser()
    for name in ['binaries', 'config', 'tls', 'workspace']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        print(json.dumps(run(args), indent=2))
    except Exception:
        raise SystemExit('Isolated signal smoke failed; inspect private root-owned run logs')


if __name__ == '__main__':
    main()
