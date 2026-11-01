import argparse
import copy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import ssl
import subprocess
import threading
import time
import urllib.parse
import urllib.request


def literal(value):
    if isinstance(value, dict):
        return {key: literal(item) for key, item in value.items()}
    if isinstance(value, list):
        return [literal(item) for item in value]
    return value.replace('$', '$$') if isinstance(value, str) else value


def metrics(counter, gauge):
    text = '# TYPE smoke_requests_total counter\nsmoke_requests_total ' + str(counter) + '\n'
    if gauge:
        text += '# TYPE smoke_value gauge\nsmoke_value{region="test"} 42\n'
    return text + '''# TYPE smoke_duration_seconds histogram
smoke_duration_seconds_bucket{le="0.1"} 2
smoke_duration_seconds_bucket{le="1"} 3
smoke_duration_seconds_bucket{le="+Inf"} 3
smoke_duration_seconds_sum 0.4
smoke_duration_seconds_count 3
# TYPE smoke_summary summary
smoke_summary{quantile="0.5"} 0.1
smoke_summary_sum 0.4
smoke_summary_count 3
'''


def query(port, context, expression='{__name__=~"smoke_.+|up"}'):
    parameters = urllib.parse.urlencode({'query': expression})
    with urllib.request.urlopen('https://127.0.0.1:' + str(port) + '/api/v1/query?' + parameters,
                                context=context, timeout=5) as response:
        document = json.load(response)
    if document.get('status') != 'success':
        raise ValueError('Synthetic PromQL query failed')
    return {tuple(sorted(item['metric'].items())): item['value'][1] for item in document['data']['result']}


def semantic_series_view(series):
    result = {}
    for key, value in series.items():
        attributes = dict(key)
        numeric_label = {'smoke_duration_seconds_bucket': 'le', 'smoke_summary': 'quantile'}.get(attributes.get('__name__'))
        if numeric_label in attributes:
            value_float = float(attributes[numeric_label])
            if math.isnan(value_float):
                raise ValueError('Numeric histogram/summary labels cannot be NaN')
            attributes[numeric_label] = value_float.hex()
        normalized = tuple(sorted(attributes.items()))
        if normalized in result:
            raise ValueError('OTLP semantic comparison would merge distinct series')
        result[normalized] = value
    return result


def equivalent_series(legacy, shadow):
    return semantic_series_view(legacy) == semantic_series_view(shadow)


def promql_checks(context, reset):
    pairs = [
        ('histogram_quantile', 'histogram_quantile(0.5, sum by (le) (smoke_duration_seconds_bucket))', None, 0.075),
        ('histogram_count', 'sum(smoke_duration_seconds_count)', None, 3),
        ('histogram_sum', 'sum(smoke_duration_seconds_sum)', None, 0.4),
        ('summary_quantile', 'sum(smoke_summary{quantile="0.5"})', None, 0.1),
        ('summary_count', 'sum(smoke_summary_count)', None, 3),
        ('infinite_bucket', 'sum(smoke_duration_seconds_bucket{le="+Inf"})', None, 3),
        ('numeric_bucket_selector', r'sum(smoke_duration_seconds_bucket{le=~"1(\\.0)?"})', None, 3),
    ]
    if reset:
        pairs.append(('counter_resets', 'sum(resets(smoke_requests_total[1m]))', None, 1))
    for name, legacy_expression, otlp_expression, expected in pairs:
        for port, expression in [(19090, legacy_expression), (29090, otlp_expression or legacy_expression)]:
            values = list(query(port, context, expression).values())
            if len(values) != 1 or not math.isclose(float(values[0]), expected, rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError('Synthetic PromQL regression failed: ' + name)
    return len(pairs)


def run(args):
    if os.readlink('/proc/self/ns/net') == os.readlink('/proc/1/ns/net'):
        raise ValueError('A separate network namespace is mandatory')
    args.workspace.mkdir(mode=0o700, exist_ok=False)
    state = {'counter': 17, 'gauge': True}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = metrics(state['counter'], state['gauge']).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *unused):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 19100), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = {'global': {'scrape_interval': '5s', 'scrape_timeout': '4s'}, 'scrape_configs': [{
        'job_name': 'synthetic-source', 'static_configs': [{'targets': ['127.0.0.1:19100'],
        'labels': {'job': 'synthetic-source', 'instance': 'legacy-node:9100', 'pod': 'synthetic-compatibility-alias'}}],
        'relabel_configs': [{'source_labels': ['__address__'], 'regex': '127.0.0.1:(.*)$',
                            'target_label': 'fixture_port', 'replacement': '$1'}]}]}
    web = {'tls_server_config': {'cert_file': str(args.tls / 'server.crt'), 'key_file': str(args.tls / 'server.key'),
                                'client_ca_file': str(args.tls / 'ca.crt'), 'client_auth_type': 'RequireAndVerifyClientCert'}}
    (args.workspace / 'web.json').write_text(json.dumps(web))
    context = ssl.create_default_context(cafile=str(args.tls / 'ca.crt'))
    context.load_cert_chain(str(args.tls / 'client.crt'), str(args.tls / 'client.key'))
    environment = {**os.environ, 'OTEL_TLS_DIR': str(args.tls), 'OTEL_STORAGE_DIR': str(args.workspace / 'queues'),
                   'OTEL_BIND_IP': '127.0.0.1', 'OTEL_METRICS_ENDPOINT': 'https://127.0.0.1:29090/api/v1/otlp'}
    children = []
    logs = []
    phases = []
    try:
        for name, port in [('legacy', 19090), ('shadow', 29090)]:
            document = copy.deepcopy(source) if name == 'legacy' else {
                'global': {'scrape_interval': '5s'}, 'scrape_configs': [],
                'storage': {'tsdb': {'out_of_order_time_window': '30m'}},
                'otlp': {'translation_strategy': 'NoTranslation', 'promote_scope_metadata': False}}
            path = args.workspace / (name + '.json')
            path.write_text(json.dumps(document))
            binary = args.legacy_prometheus if name == 'legacy' and args.legacy_prometheus else args.prometheus
            command = [str(binary), '--config.file=' + str(path),
                       '--storage.tsdb.path=' + str(args.workspace / name), '--web.listen-address=127.0.0.1:' + str(port),
                       '--web.config.file=' + str(args.workspace / 'web.json')]
            if name == 'shadow':
                command.append('--web.enable-otlp-receiver')
            log = (args.workspace / (name + '.log')).open('x')
            logs.append(log)
            children.append(subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT))
        collector = json.loads(args.config.read_text())
        collector['receivers'] = {'prometheus': {'config': literal(source), 'trim_metric_suffixes': False}}
        collector['processors'] = {key: collector['processors'][key] for key in ['memory_limiter', 'batch/metrics']}
        collector['exporters'] = {'otlp_http/metrics': collector['exporters']['otlp_http/metrics']}
        collector['extensions'] = {'file_storage': collector['extensions']['file_storage']}
        collector['service']['extensions'] = ['file_storage']
        collector['service']['pipelines'] = {'metrics': {'receivers': ['prometheus'],
            'processors': ['memory_limiter', 'batch/metrics'], 'exporters': ['otlp_http/metrics']}}
        path = args.workspace / 'collector.json'
        path.write_text(json.dumps(collector))
        log = (args.workspace / 'collector.log').open('x')
        logs.append(log)
        children.append(subprocess.Popen([str(args.binary), '--config=' + str(path)], env=environment,
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT))
        for phase, counter, gauge in [('initial', 17, True), ('counter-reset', 2, True), ('staleness', 7, False)]:
            state.update(counter=counter, gauge=gauge)
            started = time.monotonic()
            deadline = started + (45 if phase == 'initial' else 15)
            legacy = shadow = {}
            while True:
                if any(process.poll() is not None for process in children):
                    raise RuntimeError('Synthetic service stopped; inspect private smoke logs')
                try:
                    legacy, shadow = query(19090, context), query(29090, context)
                    names = {dict(key)['__name__'] for key in shadow}
                    counters = [value for key, value in shadow.items() if dict(key)['__name__'] == 'smoke_requests_total']
                    availability = [value for key, value in shadow.items() if dict(key)['__name__'] == 'up']
                    equivalent = equivalent_series(legacy, shadow)
                    if (equivalent and availability == ['1'] and counters == [str(counter)] and ('smoke_value' in names) == gauge
                            and {'smoke_duration_seconds_bucket', 'smoke_duration_seconds_sum', 'smoke_duration_seconds_count',
                                 'smoke_summary', 'smoke_summary_sum', 'smoke_summary_count', 'up'} <= names
                            and all(dict(key).get('fixture_port') == '19100' for key in shadow)):
                        checked_queries = promql_checks(context, phase != 'initial')
                        phases.append({'promqlChecks': checked_queries, 'phase': phase, 'elapsedSeconds': round(time.monotonic() - started, 3), 'seriesCount': len(shadow), 'rawLabelSetsEquivalent': legacy == shadow})
                        break
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    (args.workspace / 'comparison.json').write_text(json.dumps({name: [{'labels': dict(key), 'value': value} for key, value in data.items()] for name, data in [('legacy', legacy), ('shadow', shadow)]}, indent=2))
                    raise RuntimeError('Synthetic metric equivalence or freshness check failed; inspect private workspace')
                time.sleep(0.2)
    finally:
        for process in reversed(children):
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    result = {'schemaVersion': 1, 'observedAt': datetime.now(timezone.utc).isoformat(),
              'syntheticSourcesOnly': True, 'productionModified': False, 'productionDeployed': False,
              'separateNetworkNamespace': True, 'tlsAuthenticatedShadowReceiver': True,
              'rawNamesLabelsAndValuesIdentical': all(phase['rawLabelSetsEquivalent'] for phase in phases),
              'semanticMetricsEquivalent': True, 'comparisonMode': 'standard-otlp-semantic',
              'numericLabelNormalizationAccepted': True, 'promqlRegressionVerified': True, 'readyForCutover': False, 'counterResetVerified': True, 'stalenessVerified': True,
              'classicHistogramAndSummaryValuesVerified': True, 'literalRelabelReplacementVerified': True,
              'realSourceCompatibilityVerified': False, 'phases': phases,
              'legacyVersion': subprocess.check_output([str(args.legacy_prometheus or args.prometheus), '--version'], text=True, timeout=10).splitlines()[0],
              'shadowVersion': subprocess.check_output([str(args.prometheus), '--version'], text=True, timeout=10).splitlines()[0]}
    (args.workspace / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser()
    for name in ['binary', 'prometheus', 'config', 'tls', 'workspace']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--legacy-prometheus', type=Path)
    os.umask(0o077)
    print(json.dumps(run(parser.parse_args()), indent=2))


if __name__ == '__main__':
    main()
