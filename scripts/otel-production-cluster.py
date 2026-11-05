"""Prepare / switch a stock Collector sidecar to the native loopback Prometheus OTLP receiver.

All cross-host OTLP uses cert-manager mTLS. Native Prometheus HTTP remains
loopback-only after cutover; no protocol translation proxy or custom gateway.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('production_bootstrap', Path(__file__).with_name('otel-production-bootstrap.py'))
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
kube = bootstrap.kube
NS = bootstrap.NS
PROM = 'kube-prometheus-stack-prometheus'


def state():
    try:
        return kube('-n', NS, 'get', 'configmap', 'otel-production-state', '-o', 'json')['data']
    except RuntimeError:
        obj = bootstrap.resource('ConfigMap', 'otel-production-state', api='v1')
        obj.update(immutable=True, data={'logIngestionStartNs': str(time.time_ns()), 'riskAcceptance': 'operator-risk-acceptance-20261031.json'})
        kube('create', '-f', '-', '-o', 'json', document=obj)
        return obj['data']


def configure(bundle, cutover):
    config = yaml.safe_load((ROOT / 'deploy/monitoring/otel/cluster.yaml').read_text())
    config['exporters']['otlp_http/metrics']['endpoint'] = 'http://127.0.0.1:9090/api/v1/otlp'
    config['exporters']['otlp_http/metrics']['tls'] = {'insecure': True}
    if not cutover:
        config['service']['pipelines']['metrics']['receivers'] = ['otlp']
    scrape = yaml.safe_load((bundle / 'cluster.yaml').read_text())
    contract = json.loads((bundle / 'contract.json').read_text())
    replacements = {ref['mountPath']: '/etc/otel/source-auth/source-' + str(index) for index, ref in enumerate(contract['requiredSecretKeys'])}
    def rewrite(value):
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        return replacements.get(value, value) if isinstance(value, str) else value
    scrape = rewrite(scrape)
    # The native HTTP receiver will bind only loopback; preserve original self-target labels.
    targets = json.loads((bundle / 'original-targets.json').read_text())['activeTargets']
    for index, job in enumerate(scrape['scrape_configs']):
        self_targets = [target for target in targets if target['scrapePool'] == job['job_name'] and target['labels'].get('pod') == 'prometheus-' + PROM + '-0' and urlparse(target['scrapeUrl']).port in (9090, 8080, 10902)]
        if self_targets:
            if len(self_targets) != 1:
                raise ValueError('Exactly one native Prometheus self target required')
            scrape['scrape_configs'][index] = {'job_name': job['job_name'], 'scrape_interval': '5s', 'scrape_timeout': '4s',
                'static_configs': [{'targets': ['127.0.0.1:' + str(urlparse(self_targets[0]['scrapeUrl']).port)], 'labels': self_targets[0]['labels']}],
                'honor_labels': job.get('honor_labels', False), 'metric_relabel_configs': job.get('metric_relabel_configs', [])}
    # Old captured bundles must also retain the declarative logging monitor.
    scrape_spec = importlib.util.spec_from_file_location('native_scrape', ROOT / 'scripts/otel-scrape-config.py')
    native_scrape = importlib.util.module_from_spec(scrape_spec)
    scrape_spec.loader.exec_module(native_scrape)
    scrape = native_scrape.refresh_public_edge_probe(native_scrape.add_logging_self_monitoring(scrape))
    cm = bootstrap.resource('ConfigMap', 'otel-cluster-config', api='v1')
    cm['data'] = {'collector.yaml': yaml.safe_dump(config, sort_keys=False), 'scrape.yaml': yaml.safe_dump(scrape, sort_keys=False)}
    kube('apply', '-f', '-', '-o', 'json', document=cm)
    return contract


def run(bundle, output, cutover):
    os.umask(0o077)
    output.mkdir(mode=0o700, exist_ok=True)
    current = kube('-n', NS, 'get', 'prometheus', PROM, '-o', 'json')
    before = output / 'prometheus-before.json'
    if not before.exists():
        before.write_text(json.dumps(current))
    boundary = state()['logIngestionStartNs']
    contract = configure(bundle, cutover)
    pod = json.loads((output / 'pod-before.json').read_text())
    volume = next(mount for container in pod['spec']['containers'] if container['name'] == 'prometheus' for mount in container['volumeMounts'] if mount['mountPath'] == '/prometheus')
    locked = json.loads((ROOT / 'deploy/monitoring/otel-images.lock.json').read_text())['images']['collector']
    container = {'name': 'otel-cluster', 'image': locked['repository'] + '@' + locked['linuxAMD64Digest'], 'imagePullPolicy': 'IfNotPresent',
        'args': ['--config=/etc/otel/config/collector.yaml'], 'ports': [{'name': 'otel-grpc', 'containerPort': 4317, 'hostPort': 4317, 'hostIP': '10.250.0.1'}],
        'resources': {'requests': {'memory': '256Mi', 'cpu': '100m'}, 'limits': {'memory': '1Gi'}},
        'env': [{'name': key, 'value': value} for key, value in {'OTEL_BIND_IP': '0.0.0.0', 'OTEL_TLS_DIR': '/etc/otel/tls',
           'OTEL_STORAGE_DIR': '/var/lib/otel-data/otel-cluster', 'OTEL_SCRAPE_CONFIG': '/etc/otel/config/scrape.yaml',
           'OTEL_LOG_INGESTION_START_NS': boundary, 'OTEL_LOKI_ENDPOINT': 'https://10.250.0.3:3100/otlp',
           'OTEL_TRACE_GATEWAY_ENDPOINT': '10.250.0.1:44317', 'GOMEMLIMIT': '768MiB', 'GOMAXPROCS': '2'}.items()],
        'securityContext': {'runAsNonRoot': True, 'runAsUser': 1000, 'runAsGroup': 2000, 'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
        'volumeMounts': [{'name': 'otel-config', 'mountPath': '/etc/otel/config', 'readOnly': True},
           {'name': 'otel-tls', 'mountPath': '/etc/otel/tls', 'readOnly': True}, {'name': 'otel-source-auth', 'mountPath': '/etc/otel/source-auth', 'readOnly': True},
           {'name': 'otel-source-tls', 'mountPath': '/etc/prometheus/certs', 'readOnly': True},
           {**volume, 'mountPath': '/var/lib/otel-data'}],
        'readinessProbe': {'httpGet': {'path': '/', 'port': 13133}, 'periodSeconds': 5},
        'livenessProbe': {'httpGet': {'path': '/', 'port': 13133}, 'periodSeconds': 10, 'initialDelaySeconds': 20}}
    volumes = [value for value in current['spec'].get('volumes', []) if value['name'] not in ['otel-config', 'otel-tls', 'otel-source-auth', 'otel-source-tls']]
    volumes.extend([{'name': 'otel-source-tls', 'secret': {'secretName': 'otel-source-auth', 'defaultMode': 0o440, 'items': [
         {'key': 'tls-0', 'path': '0_cattle-monitoring-system_kube-prometheus-stack-admission_ca'},
         {'key': 'tls-1', 'path': '1_cattle-monitoring-system_kube-root-ca.crt_ca.crt'}]}}, {'name': 'otel-config', 'configMap': {'name': 'otel-cluster-config'}},
        {'name': 'otel-source-auth', 'secret': {'secretName': 'otel-source-auth', 'defaultMode': 0o440}},
        {'name': 'otel-tls', 'secret': {'secretName': 'otel-tls-cluster', 'defaultMode': 0o440, 'items':
         [{'key': key, 'path': name} for key, name in [('ca.crt', 'ca.crt'), ('tls.crt', 'server.crt'), ('tls.key', 'server.key'), ('tls.crt', 'client.crt'), ('tls.key', 'client.key')]]}}])
    containers = [value for value in current['spec'].get('containers', []) if value['name'] != 'otel-cluster'] + [container]
    cluster_config = kube('-n', NS, 'get', 'configmap', 'otel-cluster-config', '-o', 'json')['data']
    digest = hashlib.sha256(json.dumps(cluster_config, sort_keys=True).encode()).hexdigest()
    metadata = copy.deepcopy(current['spec'].get('podMetadata', {}))
    metadata.setdefault('annotations', {})['homelab.alchemmist.xyz/otel-config-sha256'] = digest
    change = {'volumes': volumes, 'containers': containers, 'podMetadata': metadata}
    if cutover:
        selector = {'matchLabels': {'homelab.alchemmist.xyz/scrape-owner': 'retired-legacy-prometheus'}}
        change.update(enableOTLPReceiver=True, listenLocal=True, evaluationInterval='5s', otlp={'translationStrategy': 'NoTranslation', 'promoteScopeMetadata': False},
                      tsdb={**current['spec'].get('tsdb', {}), 'outOfOrderTimeWindow': '30m'})
        for key in ['serviceMonitorSelector', 'podMonitorSelector', 'probeSelector', 'scrapeConfigSelector']:
            change[key] = selector
        probes = {key: {'exec': {'command': ['/bin/promtool', 'check', 'healthy' if key == 'livenessProbe' else 'ready', '--url=http://127.0.0.1:9090']}}
                  for key in ['startupProbe', 'readinessProbe', 'livenessProbe']}
        existing = next((value for value in containers if value['name'] == 'prometheus'), {'name': 'prometheus'})
        change['containers'] = [value for value in containers if value['name'] != 'prometheus'] + [{**existing, **probes}]
    kube('-n', NS, 'patch', 'prometheus', PROM, '--type=merge', '-p', json.dumps({'spec': change}), '-o', 'json')
    (output / ('cluster-cutover-request.json' if cutover else 'cluster-prepare-request.json')).write_text(json.dumps({'requested': True, 'cutover': cutover,
                     'expectedTargets': contract['activeTargetCount'], 'logIngestionStartNs': boundary, 'originalDataDeleted': False}))
    print(json.dumps({'requested': True, 'cutover': cutover, 'logIngestionStartNs': boundary}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cutover', action='store_true')
    args = parser.parse_args()
    run(args.bundle, args.output, args.cutover)
