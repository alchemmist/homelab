"""Synthetic-only all-signal durable outage/restart/recovery on isolated loopback.

Does not stop/reconfigure production or import historical data. Exact synthetic
metric timestamps/values and log multiplicity are checked, not just readiness.
"""
import argparse
import base64
import socket
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
import urllib.parse
import urllib.request

SERVICE = 'homelab-isolated-operational-replay'


def fixtures(now):
    base_ms = (now // 10**9 - 45) * 1000
    expected = [[(base_ms + i * 5000) / 1000, str(i)] for i in range(9)]
    resource = {'attributes': [{'key': 'service.name', 'value': {'stringValue': SERVICE}}]}
    metrics = {'resourceMetrics': [{'resource': resource, 'scopeMetrics': [{'metrics': [{'name': 'homelab_ops_probe',
        'gauge': {'dataPoints': [{'timeUnixNano': str(int(t * 1000) * 10**6), 'asDouble': int(v),
            'attributes': [{'key': 'source', 'value': {'stringValue': 'isolated'}}]} for t, v in expected]}}]}]}]}
    logs = {'resourceLogs': [{'resource': resource, 'scopeLogs': [{'logRecords': [
        {'timeUnixNano': str(now + i * 1000), 'body': {'stringValue': 'ops-replay-log-%02d' % i}} for i in range(24)]}]}]}
    ids = [hashlib.sha256(('operational-replay-%d' % i).encode()).hexdigest() for i in range(9)]
    traces = {'resourceSpans': [{'resource': resource, 'scopeSpans': [{'spans': [
        {'traceId': identity[:32], 'spanId': identity[32:48], 'name': 'ops-mandatory-%d' % i, 'kind': 2,
         'startTimeUnixNano': str(now - 3 * 10**9), 'endTimeUnixNano': str(now), 'status': {'code': 2}}
        for i, identity in enumerate(ids)]}]}]}
    return metrics, logs, traces, expected, {x[:32] for x in ids}


def check_metrics(document, expected):
    if document.get('status') != 'success' or document.get('warnings') or document['data'].get('resultType') != 'matrix':
        return False
    result = document['data']['result']
    return len(result) == 1 and result[0]['values'] == expected


def rollback_candidate(original):
    candidate = json.loads(original)
    processor = candidate['processors']['batch/metrics']
    processor['timeout'] = '2s' if processor['timeout'] != '2s' else '3s'
    return json.dumps(candidate).encode()


def trace_records(document):
    found = []
    def walk(value):
        if isinstance(value, dict):
            if all(key in value for key in ['traceId', 'spanId', 'name']):
                identity = value['traceId']
                if len(identity) != 32:
                    identity = base64.b64decode(identity, validate=True).hex()
                found.append((identity.lower(), value['name']))
            for child in value.values():walk(child)
        elif isinstance(value, list):
            for child in value:walk(child)
    walk(document)
    return found


def run(args):
    if os.geteuid() != 0 or os.readlink('/proc/self/ns/net') == os.readlink('/proc/1/ns/net'):
        raise ValueError('Root-owned isolated network namespace required')
    args.workspace.mkdir(mode=0o700)
    root = args.workspace
    configs = {name: json.loads((args.config / (name + '.json')).read_text()) for name in ['cluster', 'trace-gateway', 'loki', 'tempo']}
    cluster, gateway = configs['cluster'], configs['trace-gateway']
    cluster['receivers'] = {'otlp': {'protocols': {'http': cluster['receivers']['otlp']['protocols']['http']}}}
    cluster['receivers']['otlp']['protocols']['http']['endpoint'] = '127.0.0.1:4318'
    cluster['service']['pipelines']['metrics']['receivers'] = ['otlp']
    cluster['extensions'].pop('health_check', None)
    cluster['service']['extensions'] = ['file_storage']
    cluster['processors']['batch/metrics'].update(send_batch_size=2, send_batch_max_size=2)
    for name, config, port in [('cluster', cluster, 18888), ('trace-gateway', gateway, 18889)]:
        config['service']['telemetry'] = {'metrics': {'readers': [{'pull': {'exporter': {'prometheus': {'host': '127.0.0.1', 'port': port}}}}]}}
    gateway['receivers']['otlp']['protocols']['grpc']['endpoint'] = '127.0.0.1:14317'
    gateway['processors']['batch'].update(send_batch_size=1, send_batch_max_size=2)
    configs['tempo']['distributor']['receivers']['otlp']['protocols']['grpc']['endpoint'] = '127.0.0.1:24317'
    configs['tempo']['memberlist']['advertise_addr'] = '127.0.0.1'
    boundary = time.time_ns() - 10**9
    environment = {**os.environ, 'OTEL_BIND_IP': '127.0.0.1', 'OTEL_TLS_DIR': str(args.tls),
        'OTEL_STORAGE_DIR': str(root / 'state'), 'OTEL_LOG_INGESTION_START_NS': str(boundary),
        'OTEL_LOKI_ENDPOINT': 'https://127.0.0.1:3100/otlp', 'OTEL_TRACE_GATEWAY_ENDPOINT': '127.0.0.1:14317',
        'OTEL_TEMPO_ENDPOINT': '127.0.0.1:24317', 'OTEL_METRICS_ENDPOINT': 'https://127.0.0.1:29090/api/v1/otlp'}
    for name, config in configs.items():
        (root / (name + '.json')).write_text(json.dumps(config))
    (root / 'prometheus.json').write_text(json.dumps({'global': {'scrape_interval': '5s', 'scrape_timeout': '4s'}, 'scrape_configs': [],
        'storage': {'tsdb': {'out_of_order_time_window': '30m'}},
        'otlp': {'translation_strategy': 'NoTranslation', 'promote_scope_metadata': False}}))
    (root / 'web.json').write_text(json.dumps({'tls_server_config': {'cert_file': str(args.tls / 'server.crt'), 'key_file': str(args.tls / 'server.key'),
        'client_auth_type': 'RequireAndVerifyClientCert', 'client_ca_file': str(args.tls / 'ca.crt')}}))
    context = ssl.create_default_context(cafile=str(args.tls / 'ca.crt'))
    context.load_cert_chain(str(args.tls / 'client.crt'), str(args.tls / 'client.key'))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    children, generations = {}, {}
    report = {'success': False, 'syntheticOnly': True, 'productionModified': False, 'networkNamespaceIsolated': True,
              'node': 'socrat-0', 'allSignalDurableRecoveryVerified': False, 'productionOwnershipRollbackExercised': False,
              'fullOperationalAcceptance': False, 'errors': [],
              'queryClientTlsPolicy': 'strict verified mTLS, TLS1.3 minimum, default curves'}
    def save():
        (root / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    def request(port, path, body=None):
        payload = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request('https://127.0.0.1:%d%s' % (port, path), data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, context=context, timeout=4) as response:
            data = response.read(4 * 1024**2 + 1)
        if len(data) > 4 * 1024**2:
            raise ValueError('Bounded synthetic response exceeded')
        return json.loads(data) if data and path not in ['/ready', '/-/ready'] else {}
    def start(name):
        if name in children and children[name].poll() is None:
            raise ValueError('Duplicate synthetic process')
        generations[name] = generations.get(name, 0) + 1
        if name == 'prometheus':
            command = [str(args.binaries / name), '--config.file=' + str(root / 'prometheus.json'), '--storage.tsdb.path=' + str(root / 'prometheus-data'),
                       '--web.listen-address=127.0.0.1:29090', '--web.config.file=' + str(root / 'web.json'), '--web.enable-otlp-receiver']
        elif name in ['cluster', 'trace-gateway']:
            command = [str(args.binaries / 'otelcol-contrib'), '--config=' + str(root / (name + '.json'))]
        else:
            command = [str(args.binaries / name), '-config.file=' + str(root / (name + '.json')), '-config.expand-env=true']
        with (root / ('%s-%d.log' % (name, generations[name]))).open('x') as log:
            children[name] = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    def stop(name):
        process = children[name]
        if process.poll() is not None:
            raise ValueError('Synthetic process exited before controlled stop')
        process.terminate()
        process.wait(timeout=20)
        if process.returncode != 0:
            raise ValueError('Synthetic process graceful stop failed')
    def wait(check, seconds=100):
        end = time.monotonic() + seconds
        while True:
            try:
                if check():return
            except (OSError, ValueError) as error:
                if isinstance(error, ssl.SSLCertVerificationError) or isinstance(getattr(error, 'reason', None), ssl.SSLCertVerificationError):
                    raise
                pass
            if time.monotonic() >= end:raise TimeoutError('Bounded synthetic phase failed')
            time.sleep(1)
    def ready():
        for port, path in [(29090, '/-/ready'), (3100, '/ready'), (3200, '/ready')]:
            try:
                request(port, path)
                report.setdefault('backendReadiness', {})[str(port)] = 'ready'
            except Exception as error:
                report.setdefault('backendReadiness', {})[str(port)] = type(error).__name__ + ': ' + str(error)[:180]
                raise
        return True
    def queues():
        result = {}
        for port in [18888, 18889]:
            with urllib.request.urlopen('http://127.0.0.1:%d/metrics' % port, timeout=4) as response:
                lines = response.read(2 * 1024**2).decode().splitlines()
            result[str(port)] = [line for line in lines if line.startswith('otelcol_exporter_queue_size{')]
        return result
    save()
    try:
        for name in ['prometheus', 'loki', 'tempo', 'trace-gateway', 'cluster']:start(name)
        wait(ready)
        anonymous = ssl.create_default_context(cafile=str(args.tls / 'ca.crt'))
        anonymous.minimum_version = ssl.TLSVersion.TLSv1_3
        denied = []
        for port, path in [(29090, '/-/ready'), (3100, '/ready'), (3200, '/ready'), (4318, '/v1/metrics')]:
            try:
                with urllib.request.urlopen('https://127.0.0.1:%d%s' % (port, path), context=anonymous, timeout=4):
                    raise ValueError('Synthetic endpoint accepted anonymous TLS client')
            except ssl.SSLError:
                denied.append(port)
            except OSError as error:
                if isinstance(getattr(error, 'reason', None), ssl.SSLError):
                    denied.append(port)
                else:
                    raise
        report['anonymousClientRejectedPorts'] = denied
        for name in ['prometheus', 'loki', 'tempo']:stop(name)
        outage_start = time.monotonic()
        metrics, logs, traces, expected, ids = fixtures(time.time_ns())
        def ingress_ready():
            with socket.create_connection(('127.0.0.1', 4318), timeout=4) as connection:
                with context.wrap_socket(connection, server_hostname='127.0.0.1'):
                    return True
        wait(ingress_ready, seconds=15)
        # Never retry a fixture POST: an ambiguous response is a failed run,
        # not permission to change fixture multiplicity by resending it.
        for path, body in [('/v1/metrics', metrics), ('/v1/logs', logs), ('/v1/traces', traces)]:
            response = request(4318, path, body)
            if response.get('partialSuccess'):
                raise ValueError('Synthetic OTLP partial success is not full acceptance')
        # Full 30s tail decision must finish BEFORE gateway restart; never claim
        # restart durability for unsampled, in-memory tail-sampling state.
        time.sleep(42)
        report['outageQueueMetricsBeforeRestart'] = queues()
        preimage = (root / 'cluster.json').read_bytes()
        (root / 'cluster-config-preimage.json').write_bytes(preimage)
        candidate = rollback_candidate(preimage)
        for name in ['cluster', 'trace-gateway']:stop(name)
        (root / 'cluster.json').write_bytes(candidate)
        report['durableQueueFiles'] = [{'path': str(p.relative_to(root)), 'bytes': p.stat().st_size}
            for p in (root / 'state').rglob('*') if p.is_file() and ('cluster' in p.parts or 'traces' in p.parts)]
        if not report['durableQueueFiles']:raise ValueError('No durable queue files')
        for name in ['trace-gateway', 'cluster']:start(name)
        time.sleep(3)
        report['outageQueueMetricsAfterRestart'] = queues()
        stop('cluster')
        (root / 'cluster.json').write_bytes((root / 'cluster-config-preimage.json').read_bytes())
        if (root / 'cluster.json').read_bytes() != preimage:
            raise ValueError('Exact configuration preimage restore failed')
        start('cluster')
        time.sleep(3)
        report['outageQueueMetricsAfterConfigRollback'] = queues()
        report['configurationRollback'] = {'preimageSHA256': hashlib.sha256(preimage).hexdigest(),
            'candidateSHA256': hashlib.sha256(candidate).hexdigest(),
            'restoredSHA256': hashlib.sha256((root / 'cluster.json').read_bytes()).hexdigest(),
            'exactBytesRestoredWhileBackendsUnavailable': True, 'productionOwnershipRollbackExercised': False}
        for name in ['prometheus', 'loki', 'tempo']:start(name)
        wait(ready)
        metrics_query = '/api/v1/query?' + urllib.parse.urlencode({'query': 'homelab_ops_probe{source="isolated"}[10m]'})
        logs_query = '/loki/api/v1/query_range?' + urllib.parse.urlencode({'query': '{service_name="' + SERVICE + '"}', 'start': str(boundary), 'limit': 100})
        def recovered():
            metric_document = request(29090, metrics_query)
            log_document = request(3100, logs_query)
            values = [entry[1] for stream in log_document.get('data', {}).get('result', []) for entry in stream['values']]
            expected_logs = {'ops-replay-log-%02d' % i for i in range(24)}
            report['lastRecoveryCounts'] = {'metricSeries': len(metric_document.get('data', {}).get('result', [])),
                'metricPoints': sum(len(item.get('values', [])) for item in metric_document.get('data', {}).get('result', [])),
                'metricTimestampsValuesAndMultiplicityExact': check_metrics(metric_document, expected),
                'logRecords': len(values), 'logBodiesAndMultiplicityExact': len(values) == 24 and set(values) == expected_logs}
            if not check_metrics(metric_document, expected) or len(values) != 24 or set(values) != expected_logs:return False
            for identity in ids:
                body = request(3200, '/api/traces/' + identity)
                spans = trace_records(body)
                if len(spans) != 1 or spans[0][0] != identity or not spans[0][1].startswith('ops-mandatory-'):return False
            return True
        wait(recovered, seconds=140)
        report.update(success=True, allSignalDurableRecoveryVerified=True, exactMetricPoints=9, exactLogRecords=24, mandatoryTraces=9,
                      collectorAndSamplerRestartedDuringBackendOutage=True, sourceFixturesResentAfterRestart=False,
                      isolatedCollectorConfigurationRollbackVerified=True,
                      unsampledInMemoryTailStateDurabilityClaimed=False, tailDecisionWaitSeconds=30,
                      elapsedOutageRecoverySeconds=time.monotonic() - outage_start, processGenerations=generations)
        save()
        return report
    except Exception as error:
        report['errors'].append(type(error).__name__)
        save()
        raise
    finally:
        for process in reversed(list(children.values())):
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    # Only owned synthetic children in isolated namespace.
                    process.kill(); process.wait(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['binaries', 'config', 'tls', 'workspace']:
        parser.add_argument('--' + name, type=Path, required=True)
    os.umask(0o077)
    try:print(json.dumps(run(parser.parse_args())))
    except Exception as error:
        print(json.dumps({'success': False, 'errorType': type(error).__name__, 'privateRunEvidenceRetained': True}))
        raise SystemExit(1)
