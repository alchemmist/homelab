import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / 'deploy/monitoring/otel-migration-policy.json'
NODE_PROBE = '''import json, os, socket, time
from pathlib import Path
filesystem = os.statvfs('/var/lib')
memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
print(json.dumps({'hostname': socket.gethostname(), 'observedAt': time.time(),
 'diskTotalBytes': filesystem.f_blocks * filesystem.f_frsize,
 'diskAvailableBytes': filesystem.f_bavail * filesystem.f_frsize,
 'memoryAvailableBytes': int(memory['MemAvailable'].split()[0]) * 1024}))
'''


def remote(host, arguments):
    result = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, shlex.join(arguments)],
        capture_output=True, text=True, timeout=90, check=False,
    )
    if result.returncode:
        raise RuntimeError(f'{host}: read-only probe failed (exit {result.returncode})')
    return json.loads(result.stdout)


def kube(host, namespace, *arguments):
    return remote(host, ['kubectl', '-n', namespace, *arguments])


def prometheus(host, namespace, endpoint):
    path = f'/api/v1/namespaces/{namespace}/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/{endpoint}'
    payload = kube(host, namespace, 'get', '--raw', path)
    if payload.get('status') != 'success':
        raise RuntimeError('Prometheus read-only API failed')
    return payload['data']


def monitor_summary(document):
    summaries = []
    for item in document.get('items', []):
        spec = item.get('spec', {})
        endpoints = spec.get('endpoints', spec.get('podMetricsEndpoints', []))
        metadata = item.get('metadata', {})
        summaries.append({
            'kind': item['kind'], 'namespace': metadata['namespace'], 'name': metadata['name'],
            'endpointCount': len(endpoints),
            'intervals': [endpoint.get('interval', 'inherited') for endpoint in endpoints],
            'requiresAuthentication': any(any(key in endpoint for key in (
                'authorization', 'basicAuth', 'oauth2', 'bearerTokenSecret', 'bearerTokenFile',
            )) for endpoint in endpoints),
        })
    return summaries


def native_query(host, namespace, expression):
    return remote(host, ['kubectl', '-n', namespace, 'exec', 'prometheus-kube-prometheus-stack-prometheus-0',
                         '-c', 'prometheus', '--', '/bin/promtool', 'query', 'instant', '--format=json',
                         'http://127.0.0.1:9090', expression])


def collect(policy, host):
    namespace = policy['namespace']
    nodes = {}
    for node in policy['nodes']:
        nodes[node] = remote(node, ['python3', '-c', NODE_PROBE])
    resources = kube(host, namespace, 'get', 'prometheus', '-o', 'json')['items']
    native = any(item['spec'].get('enableOTLPReceiver') and item['spec'].get('listenLocal') for item in resources)
    if native:
        points = native_query(host, namespace, 'up and (time()-timestamp(up)<20)')
        targets = [{'labels': point['metric'], 'health': 'up' if point['value'][1] == '1' else 'down',
                    'scrapeInterval': '5s', 'scrapeTimeout': '4s'} for point in points]
        if len(targets) < 78:
            raise RuntimeError('Native production has fewer than the contracted 78 fresh source targets')
    else:
        targets = prometheus(host, namespace, 'targets')['activeTargets']
    target_summaries = [{
        'job': target.get('labels', {}).get('job'),
        'instance': target.get('labels', {}).get('instance'),
        'health': target.get('health'),
        'scrapeInterval': target.get('scrapeInterval'),
        'scrapeTimeout': target.get('scrapeTimeout'),
    } for target in targets]
    prometheus_summaries = [{
        'name': item['metadata']['name'],
        'version': item['spec'].get('version'),
        'scrapeInterval': item['spec'].get('scrapeInterval'),
        'evaluationInterval': item['spec'].get('evaluationInterval'),
        'retention': item['spec'].get('retention'),
        'enableAdminAPI': item['spec'].get('enableAdminAPI', False),
        'enableOTLPReceiver': item['spec'].get('enableOTLPReceiver', False),
    } for item in resources]
    monitors = kube(host, namespace, 'get', 'servicemonitors,podmonitors,probes,scrapeconfigs', '-A', '-o', 'json')
    disk_query = urllib.parse.urlencode({'query': 'socrat_metrics_directory_bytes'})
    disk_result = native_query(host, namespace, 'socrat_metrics_directory_bytes') if native else prometheus(host, namespace, 'query?' + disk_query)['result']
    directories = [{
        'node': item['metric'].get('node'), 'role': item['metric'].get('role'),
        'bytes': int(float(item['value'][1])),
    } for item in disk_result]
    return {
        'schemaVersion': 1,
        'collectedAt': datetime.now(timezone.utc).isoformat(),
        'nodes': nodes, 'targets': target_summaries,
        'monitors': monitor_summary(monitors), 'prometheus': prometheus_summaries,
        'metricDirectories': directories,
    }


def nonnegative(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def evaluate(policy, inventory, now=None):
    now = time.time() if now is None else now
    errors = []
    capacity = {}
    if policy.get('schemaVersion') != 1 or inventory.get('schemaVersion') != 1:
        raise ValueError('Unsupported migration policy or inventory version')
    fraction = policy['minimumFreeFraction']
    if not nonnegative(fraction) or fraction < 0.2 or fraction >= 1:
        raise ValueError('Free-space fraction must be at least 0.2 and less than 1')
    maximum_age = policy['maximumObservationAgeSeconds']
    if not nonnegative(maximum_age) or not 0 < maximum_age <= 900:
        raise ValueError('Observation lifetime must be at most 900 seconds')
    for node, reservation in policy['nodes'].items():
        observed = inventory.get('nodes', {}).get(node)
        if observed is None:
            errors.append(f'{node}: missing capacity observation')
            continue
        keys = ('observedAt', 'diskTotalBytes', 'diskAvailableBytes', 'memoryAvailableBytes')
        if any(not nonnegative(observed.get(key)) for key in keys):
            errors.append(f'{node}: invalid capacity observation')
            continue
        if observed['hostname'] != node:
            errors.append(f'{node}: SSH alias resolved to a different hostname')
        age = now - observed['observedAt']
        if age < -60 or age > maximum_age:
            errors.append(f'{node}: stale or future capacity observation')
        components = reservation['components']
        values = [reservation[key] for key in (
            'minimumFreeBytes', 'projectedAdditionalDiskBytes', 'minimumAvailableMemoryBytes',
        )] + list(components.values())
        if not components or any(not nonnegative(value) for value in values):
            raise ValueError(f'{node}: invalid resource reservation')
        disk_floor = max(reservation['minimumFreeBytes'], math.ceil(observed['diskTotalBytes'] * fraction))
        disk_after = observed['diskAvailableBytes'] - reservation['projectedAdditionalDiskBytes']
        required_memory = sum(components.values()) + reservation['minimumAvailableMemoryBytes']
        capacity[node] = {
            'diskAfterPeakBytes': disk_after, 'diskFloorBytes': disk_floor,
            'memoryAvailableBytes': observed['memoryAvailableBytes'],
            'memoryRequiredBytes': required_memory,
            'additionalComponentMemoryBytes': sum(components.values()),
        }
        if disk_after < disk_floor:
            errors.append(f'{node}: projected disk space violates the reserve')
        if observed['memoryAvailableBytes'] < required_memory:
            errors.append(f'{node}: insufficient available memory for bounded component budgets and reserve')
    targets = inventory.get('targets', [])
    if not targets:
        errors.append('No live scrape targets were inventoried')
    elif any(target.get('health') != 'up' for target in targets):
        errors.append('Existing scrape targets are not all healthy')
    if not inventory.get('prometheus'):
        errors.append('Prometheus was not inventoried')
    for prerequisite in ('diskProjectionVerified', 'backupVerified', 'historyRoundtripVerified', 'historySourceIntegrityVerified', 'sourceRegistryVerified'):
        if policy.get(prerequisite) is not True:
            errors.append(f'Unverified prerequisite: {prerequisite}')
    return {'schemaVersion': 1, 'readyForCutover': not errors, 'errors': errors, 'capacity': capacity}


def save(path, document):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['collect', 'check'])
    parser.add_argument('--policy', type=Path, default=DEFAULT_POLICY)
    parser.add_argument('--ssh-host', default='socrat-0')
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        policy = json.loads(args.policy.read_text())
        if args.command == 'collect':
            document = collect(policy, args.ssh_host)
            save(args.output, document)
            print(f'Inventory saved to {args.output}')
            return 0
        if args.inventory is None:
            parser.error('check requires --inventory')
        result = evaluate(policy, json.loads(args.inventory.read_text()))
        save(args.output, result)
        print(json.dumps(result, indent=2))
        return 0 if result['readyForCutover'] else 1
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
