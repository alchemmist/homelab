import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('otel_preflight', ROOT / 'scripts/otel-migration-preflight.py')
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)
NAMESPACE = 'cattle-monitoring-system'
CLUSTER_JOBS = {
    'cattle-monitoring-system/thanos', 'litellm', 'vllm',
    'kube-prometheus-stack-alertmanager', 'apiserver', 'coredns',
    'kube-prometheus-stack-grafana', 'kube-state-metrics', 'kubelet',
    'kube-prometheus-stack-operator', 'kube-prometheus-stack-prometheus',
    'kube-prometheus-stack-thanos-discovery', 'kube-etcd',
    'service-probes-exporter', 'service-probes', 'traefik',
}
LOCAL_JOBS = {'node-exporter'}
SENSITIVE = re.compile(r'token|secret|password|cookie|credential|authorization|bearer|api[_-]?key|^key$|username', re.I)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def scrub(value, key=''):
    if SENSITIVE.search(key):
        return '<redacted>'
    if isinstance(value, dict):
        return {name: scrub(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, key) for item in value]
    if key in ('path', 'metricsPath') and isinstance(value, str) and value not in ('/metrics', '/metrics/cadvisor', '/metrics/probes', '/probe'):
        return '<redacted-path>'
    if isinstance(value, str) and '://' in value:
        try:
            return identity(value)
        except ValueError:
            return '<redacted-url>'
    return value


def monitor_key(kind, namespace, name):
    kinds = {'ServiceMonitor': 'serviceMonitor', 'PodMonitor': 'podMonitor', 'Probe': 'probe', 'ScrapeConfig': 'scrapeConfig'}
    return f'{kinds[kind]}/{namespace}/{name}'


def selected(selector, attributes):
    if any(attributes.get(key) != value for key, value in selector.get('matchLabels', {}).items()):
        return False
    for expression in selector.get('matchExpressions', []):
        key, operation = expression['key'], expression['operator']
        values = expression.get('values', [])
        if operation == 'In' and attributes.get(key) not in values:
            return False
        if operation == 'NotIn' and key in attributes and attributes[key] in values:
            return False
        if operation == 'Exists' and key not in attributes:
            return False
        if operation == 'DoesNotExist' and key in attributes:
            return False
        if operation not in ('In', 'NotIn', 'Exists', 'DoesNotExist'):
            raise ValueError('Unsupported label selector operator')
    return True


def monitor_selected(item, prometheus, namespaces):
    kind = item['kind']
    prefix = {'ServiceMonitor': 'serviceMonitor', 'PodMonitor': 'podMonitor', 'Probe': 'probe', 'ScrapeConfig': 'scrapeConfig'}[kind]
    selector = prometheus['spec'].get(prefix + 'Selector')
    if selector is None:
        return False
    metadata = item['metadata']
    if not selected(selector, metadata.get('labels', {})):
        return False
    namespace_selector = prometheus['spec'].get(prefix + 'NamespaceSelector')
    if namespace_selector is None:
        return metadata['namespace'] == prometheus['metadata']['namespace']
    return selected(namespace_selector, namespaces.get(metadata['namespace'], {}))


def identity(value):
    if '://' not in value:
        return value
    url = urllib.parse.urlsplit(value)
    host = url.hostname or '<unknown>'
    if url.port:
        host += ':' + str(url.port)
    return url.scheme + '://' + host + '/<redacted-path>#' + hashlib.sha256(value.encode()).hexdigest()[:16]


def target_summary(target):
    labels = target.get('labels', {})
    url = urllib.parse.urlsplit(target['scrapeUrl'])
    path = url.path if url.path in ('/metrics', '/metrics/cadvisor', '/metrics/probes', '/probe') else '<redacted-path>'
    pool = target['scrapePool']
    parts = pool.split('/')
    if len(parts) < 4 or not parts[-1].isdigit():
        raise ValueError('Unsupported scrape-pool identity')
    job = labels.get('job', '')
    owner = 'node-systemd-agent' if job in LOCAL_JOBS else 'cluster-collector@socrat-0' if job in CLUSTER_JOBS else None
    return {
        'scrapePool': pool, 'monitor': '/'.join(parts[:-1]), 'endpointIndex': int(parts[-1]),
        'job': job, 'identity': identity(labels.get('instance', '')),
        'labelNames': sorted(labels), 'scheme': url.scheme, 'metricsPath': path,
        'health': target.get('health'), 'scrapeInterval': target.get('scrapeInterval'),
        'scrapeTimeout': target.get('scrapeTimeout'), 'futureOwner': owner,
    }


def expressions(document):
    for panel in document.get('panels', []):
        for index, target in enumerate(panel.get('targets', [])):
            expression = target.get('expr')
            if isinstance(expression, str) and expression:
                yield panel['id'], target.get('refId', str(index)), expression
        if panel.get('panels'):
            yield from expressions({'panels': panel['panels']})


def consumers(rule_document, configmaps):
    rules = []
    for group in rule_document.get('groups', []):
        for rule in group.get('rules', []):
            expression = rule.get('query')
            if not isinstance(expression, str) or not expression:
                raise ValueError('Rule without a PromQL expression')
            rules.append({
                'group': group['name'], 'name': rule['name'], 'type': rule['type'],
                'expressionSHA256': digest(expression), 'health': rule.get('health'),
            })
    dashboards = []
    uids = set()
    for item in configmaps.get('items', []):
        for filename, content in item.get('data', {}).items():
            if not filename.endswith('.json'):
                continue
            document = json.loads(content)
            uid = document.get('uid')
            if not uid:
                raise ValueError('Dashboard has no stable UID')
            if uid in uids:
                raise ValueError('Dashboard UID is provisioned more than once')
            uids.add(uid)
            queries = [{
                'panel': panel, 'refId': ref, 'expressionSHA256': digest(expression),
            } for panel, ref, expression in expressions(document)]
            dashboards.append({'uid': uid, 'queryCount': len(queries), 'queries': queries,
                               'refresh': document.get('refresh'),
                               'sourceConfigMap': item['metadata']['namespace'] + '/' + item['metadata']['name']})
    return {'rules': rules, 'dashboards': sorted(dashboards, key=lambda item: item['uid'])}


def build(monitors, targets, prometheus, namespaces, rules, configmaps):
    namespace_labels = {item['metadata']['name']: item['metadata'].get('labels', {}) for item in namespaces['items']}
    catalog = {}
    for item in monitors['items']:
        metadata = item['metadata']
        key = monitor_key(item['kind'], metadata['namespace'], metadata['name'])
        endpoints = item['spec'].get('endpoints', item['spec'].get('podMetricsEndpoints', []))
        catalog[key] = {
            'kind': item['kind'], 'namespace': metadata['namespace'], 'name': metadata['name'],
            'resourceVersion': metadata['resourceVersion'],
            'selectedByPrometheus': monitor_selected(item, prometheus, namespace_labels),
            'specSHA256': digest(item['spec']), 'spec': scrub(item['spec']),
            'endpointCount': len(endpoints), 'activeTargetCount': 0,
        }
    active = [target_summary(target) for target in targets['activeTargets']]
    errors = []
    intervals = Counter()
    for target in active:
        key = target['monitor']
        if key not in catalog:
            errors.append('Active target has no monitor: ' + target['scrapePool'])
            continue
        entry = catalog[key]
        entry['activeTargetCount'] += 1
        if not entry['selectedByPrometheus']:
            errors.append('Active target monitor is outside the inventoried selectors: ' + key)
        if target['endpointIndex'] >= entry['endpointCount']:
            errors.append('Active target endpoint is absent: ' + target['scrapePool'])
        if target['futureOwner'] is None:
            errors.append('Unknown scrape owner for job: ' + target['job'])
        if target['health'] != 'up':
            errors.append('Unhealthy target: ' + target['scrapePool'])
        intervals[target['scrapeInterval']] += 1
    if not active:
        errors.append('No active targets')
    consumption = consumers(rules, configmaps)
    if not consumption['rules'] or not consumption['dashboards']:
        errors.append('Missing rule or dashboard consumers')
    return {
        'schemaVersion': 1, 'collectedAt': datetime.now(timezone.utc).isoformat(),
        'liveInventoryVerified': not errors, 'readyForCutover': False, 'errors': errors,
        'activeTargetCount': len(active), 'activeIntervals': dict(intervals),
        'jobTargetCounts': dict(sorted(Counter(target['job'] for target in active).items())),
        'droppedTargetCount': len(targets.get('droppedTargets', [])),
        'sources': catalog, 'targets': active, 'consumers': consumption,
        'sourceCapabilitiesVerified': False,
        'findings': [
            {'kind': 'scrape-frequency', 'targets': sum(count for interval, count in intervals.items() if interval != '5s'),
             'description': 'Non-5s live scrape intervals must be translated and load-tested; do not infer frequency from global defaults.'},
            {'kind': 'discovery', 'description': 'Unselected or empty monitors remain inventoried but are not automatically activated by migration.'},
            {'kind': 'source-refresh', 'description': 'GPU and metrics-disk source refresh still requires live timer/collector verification independently of scrape frequency.'},
            {'kind': 'fallback', 'description': 'Current node-exporter is a Kubernetes DaemonSet; native fallback collection needs an independent host source, not just a systemd OTel agent.'},
        ],
    }


HOST_PRODUCER_PROBE = """import json, re, subprocess
from pathlib import Path
files=[]
for path in sorted(Path('/var/lib/node_exporter/textfile_collector').glob('*.prom')):
    families={}
    for line in path.read_text().splitlines():
        if line.startswith('# TYPE '):
            fields=line.split()
            families[fields[2]]=fields[3]
        elif line and not line.startswith('#'):
            match=re.match(r'([a-zA-Z_:][a-zA-Z0-9_:]*)',line)
            if match:
                families.setdefault(match.group(1),'untyped')
    files.append({'file':path.name,'families':families})
result=subprocess.run(['systemctl','show','monitoring-gpu.timer','monitoring-vpn.timer',
    '--no-pager','--property=Id,LoadState,ActiveState,TimersMonotonic'],capture_output=True,text=True)
if result.returncode:
    raise RuntimeError('timer inspection failed')
print(json.dumps({'files':files,'timers':result.stdout}))
"""


def host_producers(hosts):
    result = {}
    for node in hosts:
        observed = PREFLIGHT.remote(node, ['python3', '-c', HOST_PRODUCER_PROBE])
        timers = {}
        for block in observed.pop('timers').strip().split('\n\n'):
            fields = [line.split('=', 1) for line in block.splitlines() if '=' in line]
            properties = dict(fields)
            if properties.get('LoadState') != 'loaded':
                continue
            intervals = [value for name, value in fields if name == 'TimersMonotonic']
            active_interval = next((re.search(r'OnUnitActiveUSec=([^ ;}]+)', value).group(1)
                                    for value in intervals if 'OnUnitActiveUSec=' in value), None)
            timers[properties['Id']] = {'active': properties.get('ActiveState') == 'active',
                                        'refreshInterval': active_interval}
        observed['timers'] = timers
        for item in observed['files']:
            item['producer'] = {'nvidia.prom': 'monitoring_gpu', 'vpn.prom': 'monitoring_vpn',
                                'socrat-metrics-disk.prom': 'thanos-disk-daemonset'}.get(item['file'])
        result[node] = observed
    return result


def attach_producers(registry, producers, daemonsets):
    errors = registry['errors']
    for node, observed in producers.items():
        for item in observed['files']:
            if item['producer'] is None:
                errors.append('Unregistered textfile producer on ' + node + ': ' + item['file'])
    required = [('socrat-0', 'nvidia.prom', 'monitoring-gpu.timer'),
                ('socrat-2', 'vpn.prom', 'monitoring-vpn.timer')]
    for node, filename, timer in required:
        observed = producers.get(node, {})
        if not any(item['file'] == filename for item in observed.get('files', [])):
            errors.append('Required producer file is missing: ' + node + '/' + filename)
        if not observed.get('timers', {}).get(timer, {}).get('active'):
            errors.append('Required producer timer is not active: ' + node + '/' + timer)
    disk = next((item for item in daemonsets['items'] if item['metadata']['name'] == 'thanos-disk'), None)
    if disk is None:
        errors.append('Thanos disk producer was not inventoried')
        disk_interval = None
    else:
        env = disk['spec']['template']['spec']['containers'][0].get('env', [])
        disk_interval = next((item.get('value') for item in env if item['name'] == 'INTERVAL_SECONDS'), None)
    registry['hostProducers'] = producers
    registry['diskProducerRefreshSeconds'] = disk_interval
    registry['liveInventoryVerified'] = not errors
    registry['metricsSourceRegistryVerified'] = not errors and set(producers) == {'socrat-0', 'socrat-1', 'socrat-2', 'socrat-3'}
    registry['sourceRegistryVerified'] = False
    registry['logTraceSourcesVerified'] = False
    return registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-host', default='socrat-0')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        host = args.ssh_host
        monitors = PREFLIGHT.kube(host, NAMESPACE, 'get', 'servicemonitors,podmonitors,probes,scrapeconfigs', '-A', '-o', 'json')
        targets = PREFLIGHT.prometheus(host, NAMESPACE, 'targets')
        prom = PREFLIGHT.kube(host, NAMESPACE, 'get', 'prometheus', '-o', 'json')['items']
        if len(prom) != 1:
            raise ValueError('Expected exactly one Prometheus resource')
        namespaces = PREFLIGHT.kube(host, NAMESPACE, 'get', 'namespaces', '-o', 'json')
        rules = PREFLIGHT.prometheus(host, NAMESPACE, 'rules')
        configmaps = PREFLIGHT.kube(host, NAMESPACE, 'get', 'configmaps', '-A', '-l', 'grafana_dashboard=1', '-o', 'json')
        result = build(monitors, targets, prom[0], namespaces, rules, configmaps)
        producers = host_producers(['socrat-0', 'socrat-1', 'socrat-2', 'socrat-3'])
        daemonsets = PREFLIGHT.kube(host, NAMESPACE, 'get', 'daemonsets', '-o', 'json')
        attach_producers(result, producers, daemonsets)
        PREFLIGHT.save(args.output, result)
        print(json.dumps({key: result[key] for key in ('liveInventoryVerified', 'activeTargetCount', 'activeIntervals', 'errors')}, indent=2))
        return 0 if result['liveInventoryVerified'] else 1
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
