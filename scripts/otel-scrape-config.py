import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('scrape_registry', ROOT / 'scripts/otel-source-registry.py')
REGISTRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGISTRY)
NODES = ('socrat-0', 'socrat-1', 'socrat-2', 'socrat-3')
INLINE_CREDENTIALS = {'password', 'credentials', 'bearer_token', 'client_secret'}
ASSET_ROOTS = ('/etc/otel/source-auth/', '/var/run/secrets/kubernetes.io/serviceaccount/', '/etc/prometheus/certs/', '/etc/prometheus/secrets/')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def assets(value):
    result = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in INLINE_CREDENTIALS and item:
                raise ValueError('Inline or masked credentials require explicit credential-file translation')
            if key.endswith('_file') and isinstance(item, str) and item:
                if not item.startswith(ASSET_ROOTS) or '..' in Path(item).parts:
                    raise ValueError('Unsupported source file dependency requires explicit translation')
                result.add(item)
            result.update(assets(item))
    elif isinstance(value, list):
        for item in value:
            result.update(assets(item))
    elif isinstance(value, str) and '<secret>' in value:
        raise ValueError('A redacted placeholder cannot be used as live configuration')
    return result


def translate_authorization(job, monitors):
    translated = copy.deepcopy(job)
    references = []
    authorization = translated.get('authorization', {})
    if not authorization.get('credentials'):
        return translated, references
    parts = job['job_name'].split('/')
    if len(parts) != 4 or not parts[-1].isdigit():
        raise ValueError('Inline authorization has no attributable monitor endpoint')
    monitor = monitors.get('/'.join(parts[:-1]))
    if monitor is None:
        raise ValueError('Authorization monitor was not inventoried')
    endpoints = monitor['spec'].get('endpoints', monitor['spec'].get('podMetricsEndpoints', []))
    if int(parts[-1]) >= len(endpoints):
        raise ValueError('Authorization endpoint was not inventoried')
    endpoint = endpoints[int(parts[-1])]
    source = endpoint.get('authorization', {}).get('credentials') or endpoint.get('bearerTokenSecret')
    if not isinstance(source, dict):
        raise ValueError('Inline authorization requires an explicit SecretKeySelector')
    namespace = monitor['metadata']['namespace']
    name, key = source.get('name', ''), source.get('key', '')
    if (not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', namespace)
            or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', name)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', key) or key in ('.', '..') or source.get('optional')):
        raise ValueError('Invalid or optional authorization secret reference')
    expected_type = endpoint.get('authorization', {}).get('type', 'Bearer')
    if authorization.get('type', 'Bearer') != expected_type:
        raise ValueError('Effective authorization type differs from monitor')
    if authorization.get('credentials_file'):
        raise ValueError('Ambiguous authorization credential sources')
    authorization.pop('credentials')
    authorization['credentials_file'] = '/etc/otel/source-auth/' + '/'.join((namespace, name, key))
    references.append({'namespace': namespace, 'secret': name, 'key': key,
                       'mountPath': authorization['credentials_file']})
    return translated, references


def escape_literals(value):
    if isinstance(value, dict):
        return {key: escape_literals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [escape_literals(item) for item in value]
    if isinstance(value, str):
        return value.replace('$', '$$')
    return value


def refresh_public_edge_probe(scrape):
    """Keep captured native scrape bundles aligned with the owned VPS probe."""
    targets = yaml.safe_load((ROOT / 'charts/monitoring-k3s/values.yaml').read_text())['serviceProbes']['targets']
    endpoint = next(target['url'] for target in targets if target['id'] == 'edge-vps')
    result = copy.deepcopy(scrape)
    for job in result.get('scrape_configs', []):
        if not job.get('job_name', '').startswith('serviceMonitor/cattle-monitoring-system/monitoring-service-probes/'):
            continue
        identity = [rule.get('replacement') for rule in job.get('relabel_configs', [])
                    if rule.get('target_label') == 'service_id']
        if identity == ['edge-vps']:
            if job.get('params', {}).get('module') != ['tcp_connect']:
                raise ValueError('Unexpected VPS edge probe module')
            job['params']['target'] = [endpoint]
    return result


def add_logging_self_monitoring(scrape):
    """Add only the native owner's authenticated Loki target, idempotently."""
    result = copy.deepcopy(scrape)
    job = {
        'job_name': 'otel-logging/loki', 'scrape_interval': '5s', 'scrape_timeout': '4s',
        'scheme': 'https', 'metrics_path': '/metrics',
        'tls_config': {'ca_file': '/etc/otel/tls/ca.crt',
                       'cert_file': '/etc/otel/tls/client.crt',
                       'key_file': '/etc/otel/tls/client.key',
                       'server_name': 'otel-loki.cattle-monitoring-system.svc',
                       'insecure_skip_verify': False},
        'static_configs': [{'targets': ['otel-loki.cattle-monitoring-system.svc:3100'],
                            'labels': {'job': 'otel-loki', 'scrape_owner': 'otel-cluster'}}],
    }
    existing = [j for j in result['scrape_configs'] if j['job_name'] == job['job_name']]
    if existing and existing != [job]:
        raise ValueError('Conflicting Loki self-monitoring target')
    if not existing:
        result['scrape_configs'].append(job)
    return result


def compile_config(source, targets, monitors=None):
    monitors = {} if monitors is None else monitors
    active = targets['activeTargets']
    if not active or any(target.get('health') != 'up' for target in active):
        raise ValueError('A complete healthy target inventory is required')
    pools = {}
    for target in active:
        pools.setdefault(target['scrapePool'], []).append(target)
    global_config = copy.deepcopy(source.get('global', {}))
    global_config.pop('external_labels', None)
    global_config.pop('evaluation_interval', None)
    global_config.update(scrape_interval='5s', scrape_timeout='4s')
    outputs = {name: {'global': copy.deepcopy(global_config), 'scrape_configs': []}
               for name in ('cluster', *NODES)}
    contract = {'schemaVersion': 1, 'collectedAt': datetime.now(timezone.utc).isoformat(),
                'productionModified': False, 'readyForCutover': False,
                'sourceConfigSHA256': fingerprint(source), 'sourceExternalLabelsSHA256': fingerprint(source.get('global', {}).get('external_labels', {})),
                'pools': [], 'excludedEmptyPools': [], 'requiredFileMounts': [],
                'legacyTargetIdentityAliasesRequireAcceptance': True,
                'authFilesAndRBACRuntimeVerified': False, 'receiverCompatibilityVerified': False,
                'secretAssetSynchronizationRuntimeVerified': False, 'requiredSecretKeys': []}
    seen = set()
    mounts = set(assets(global_config))
    nodes = set()
    for original in source.get('scrape_configs', []):
        pool = original['job_name']
        if pool in seen:
            raise ValueError('Duplicate scrape pool')
        seen.add(pool)
        if pool not in pools:
            contract['excludedEmptyPools'].append(pool)
            continue
        group = pools[pool]
        jobs = {target['labels'].get('job') for target in group}
        if jobs <= REGISTRY.CLUSTER_JOBS:
            owner = 'cluster'
        elif jobs <= REGISTRY.LOCAL_JOBS:
            owner = 'node-agents'
        else:
            raise ValueError('Unknown or mixed source ownership')
        translated, secret_keys = translate_authorization(original, monitors)
        for reference in secret_keys:
            if reference not in contract['requiredSecretKeys']:
                contract['requiredSecretKeys'].append(reference)
        translated.update(scrape_interval='5s', scrape_timeout='4s')
        references = assets(translated)
        mounts.update(references)
        record = {'pool': pool, 'owner': owner, 'targetCount': len(group),
                  'originalConfigSHA256': fingerprint(original), 'fileDependencies': sorted(references),
                  'targetLabelSHA256': sorted(fingerprint(target['labels']) for target in group)}
        if owner == 'cluster':
            outputs['cluster']['scrape_configs'].append(translated)
        else:
            if translated.get('scheme', 'http') != 'http' or references or any(
                    key in translated for key in ('basic_auth', 'authorization', 'oauth2', 'tls_config')):
                raise ValueError('Local exporter transport/authentication needs explicit compatibility review')
            for target in group:
                discovered = target.get('discoveredLabels', {})
                node = discovered.get('__meta_kubernetes_pod_node_name') or discovered.get('__meta_kubernetes_node_name')
                if node not in NODES or node in nodes:
                    raise ValueError('Node-exporter ownership is missing, unknown or duplicated')
                nodes.add(node)
                local = {key: copy.deepcopy(value) for key, value in translated.items()
                         if not key.endswith('_sd_configs') and key not in ('static_configs', 'relabel_configs')}
                local['static_configs'] = [{'targets': ['127.0.0.1:19100'], 'labels': copy.deepcopy(target['labels'])}]
                outputs[node]['scrape_configs'].append(local)
            record['labelMode'] = 'legacy target labels retained as explicit compatibility aliases, not host-process runtime metadata'
        contract['pools'].append(record)
    if set(pools) - seen:
        raise ValueError('Active targets are absent from the effective scrape configuration')
    if nodes != set(NODES):
        raise ValueError('Exactly one independent node source is required for every node')
    if not outputs['cluster']['scrape_configs']:
        raise ValueError('Cluster source inventory is empty')
    contract['requiredFileMounts'] = sorted(mounts)
    contract['activeTargetCount'] = len(active)
    contract['loggingSelfMonitoring'] = {
        'job': 'otel-logging/loki', 'owner': 'cluster',
        'usesExistingClusterTLSMount': True, 'additionalSecretKeys': [],
        'intervalSeconds': 5, 'timeoutSeconds': 4,
    }
    outputs['cluster'] = refresh_public_edge_probe(add_logging_self_monitoring(outputs['cluster']))
    outputs = escape_literals(outputs)
    contract['dollarEscaping'] = 'literal Prometheus dollars escaped before Collector confmap resolution'
    contract['outputSHA256'] = {name: fingerprint(document) for name, document in outputs.items()}
    return outputs, contract


def validation_config(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.endswith('_file') and isinstance(item, str) and item:
                name = {'ca_file': 'ca.crt', 'cert_file': 'client.crt', 'key_file': 'client.key'}.get(key)
                result[key] = ('${env:OTEL_TLS_DIR}/' + name) if name else '${env:OTEL_VALIDATION_ASSET_DIR}/token'
            else:
                result[key] = validation_config(item)
        return result
    if isinstance(value, list):
        return [validation_config(item) for item in value]
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-host', default='socrat-0')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        source_yaml = REGISTRY.PREFLIGHT.prometheus(args.ssh_host, REGISTRY.NAMESPACE, 'status/config')['yaml']
        source = yaml.safe_load(source_yaml)
        targets = REGISTRY.PREFLIGHT.prometheus(args.ssh_host, REGISTRY.NAMESPACE, 'targets')
        monitor_items = REGISTRY.PREFLIGHT.kube(args.ssh_host, REGISTRY.NAMESPACE, 'get', 'servicemonitors,podmonitors', '-A', '-o', 'json')['items']
        monitors = {REGISTRY.monitor_key(item['kind'], item['metadata']['namespace'], item['metadata']['name']): item for item in monitor_items}
        outputs, contract = compile_config(source, targets, monitors)
        contract['sourceYAMLTextSHA256'] = hashlib.sha256(source_yaml.encode()).hexdigest()
        args.output.mkdir(mode=0o700, exist_ok=False)
        for name, document in outputs.items():
            with (args.output / (name + '.yaml')).open('x') as stream:
                yaml.safe_dump(document, stream, sort_keys=False)
            with (args.output / ('validation-' + name + '.yaml')).open('x') as stream:
                yaml.safe_dump(validation_config(document), stream, sort_keys=False)
        contract['schemaValidationUsesInertAuthAndCAFixtures'] = True
        with (args.output / 'contract.json').open('x') as stream:
            json.dump(contract, stream, indent=2)
            stream.write('\n')
        print(json.dumps({'output': str(args.output), 'activeTargetCount': contract['activeTargetCount'],
                          'poolCount': len(contract['pools']), 'fileMountCount': len(contract['requiredFileMounts']),
                          'readyForCutover': False}, indent=2))
        return 0
    except yaml.YAMLError:
        print('Effective configuration YAML could not be decoded; raw contents are not logged', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
