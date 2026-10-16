import argparse
import base64
import json
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


NAMESPACE = 'cattle-monitoring-system'
PROMETHEUS_SERVICE = 'kube-prometheus-stack-prometheus:9090'


def kubectl(host, *args):
    result = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', host, shlex.join(['kubectl', *args])],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode:
        raise RuntimeError('kubectl failed: ' + result.stderr[-1000:])
    return json.loads(result.stdout)


def prometheus(host, endpoint, params=None):
    path = f'/api/v1/namespaces/{NAMESPACE}/services/http:{PROMETHEUS_SERVICE}/proxy/api/v1/{endpoint}'
    if params:
        path += '?' + urllib.parse.urlencode(params)
    result = kubectl(host, 'get', '--raw', path)
    if result.get('status') != 'success':
        raise RuntimeError('Prometheus API returned an unsuccessful result')
    return result['data']


def query(host, expression, timestamp=None):
    params = {'query': expression}
    if timestamp is not None:
        params['time'] = timestamp
    return prometheus(host, 'query', params)['result']


def require(condition, description):
    if not condition:
        raise RuntimeError(description)
    print('PASS:', description)


def target_summary(targets):
    summary = {}
    for target in targets:
        job = target.get('labels', {}).get('job', '<unknown>')
        counts = summary.setdefault(job, {'up': 0, 'down': 0})
        counts['up' if target.get('health') == 'up' else 'down'] += 1
    return summary


def public_status(url, credentials=None):
    headers = {}
    if credentials:
        headers['Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-host', default='socrat-0')
    parser.add_argument('--grafana-url', default='https://grafana.socrat.alchemmist.xyz')
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--wait-seconds', type=int, default=120)
    args = parser.parse_args()
    nodes = kubectl(args.ssh_host, 'get', 'nodes', '-o', 'json')['items']
    names = {node['metadata']['name'] for node in nodes}
    etcd_count = sum('node-role.kubernetes.io/etcd' in node['metadata'].get('labels', {}) for node in nodes)
    require(all(any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']) for node in nodes), f'all {len(nodes)} nodes Ready')
    deadline = time.monotonic() + max(0, args.wait_seconds)
    while True:
        targets = prometheus(args.ssh_host, 'targets')['activeTargets']
        if targets and all(target.get('health') == 'up' for target in targets):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    require(bool(targets), 'Prometheus discovered scrape targets')
    print('Target counts:', json.dumps(target_summary(targets), sort_keys=True))
    failures = [{key: target.get(key) for key in ('scrapePool', 'scrapeUrl', 'lastError')} for target in targets if target.get('health') != 'up']
    require(not failures, 'all active targets UP' + (': ' + json.dumps(failures) if failures else ''))
    checks = [
        ('count(node_uname_info)', len(nodes), 'node exporter coverage'),
        ('count(kubelet_node_name{job="kubelet"})', len(nodes), 'kubelet coverage'),
        ('count(etcd_server_has_leader{job="kube-etcd"} == 1)', etcd_count, 'etcd members have leader'),
    ]
    for expression, expected, label in checks:
        values = query(args.ssh_host, expression)
        require(len(values) == 1 and float(values[0]['value'][1]) == expected, f'{label}: expected {expected}')
    reported = {item['metric'].get('node') for item in query(args.ssh_host, 'kube_node_info')}
    require(reported == names, 'kube-state-metrics covers current node names')
    for metric in ['node_memory_MemAvailable_bytes', 'node_filesystem_avail_bytes', 'container_cpu_usage_seconds_total', 'kube_pod_container_status_restarts_total', 'apiserver_request_total', 'scheduler_pending_pods', 'workqueue_depth']:
        require(bool(query(args.ssh_host, metric)), metric + ' present')
    pvcs = kubectl(args.ssh_host, '-n', NAMESPACE, 'get', 'pvc', '-o', 'json')['items']
    require(len(pvcs) >= 3, 'Prometheus, Grafana and Alertmanager persistent claims exist')
    volumes = {volume['metadata']['name']: volume for volume in kubectl(args.ssh_host, 'get', 'pv', '-o', 'json')['items']}
    for pvc in pvcs:
        name = pvc['metadata']['name']
        require(pvc['status']['phase'] == 'Bound' and pvc['spec']['storageClassName'] == 'local-path', name + ' bound to local-path')
        volume = volumes[pvc['spec']['volumeName']]
        terms = volume['spec'].get('nodeAffinity', {}).get('required', {}).get('nodeSelectorTerms', [])
        require(bool(terms) and all(any(e['key'] == 'kubernetes.io/hostname' and e['operator'] == 'In' and e['values'] == ['socrat-1'] for e in term.get('matchExpressions', [])) for term in terms), name + ' pinned to socrat-1')
    pods = kubectl(args.ssh_host, '-n', NAMESPACE, 'get', 'pods', '-o', 'json')['items']
    for pod in pods:
        if pod['status'].get('phase') in ['Succeeded', 'Failed']:
            continue
        require(any(condition['type'] == 'Ready' and condition['status'] == 'True' for condition in pod['status'].get('conditions', [])), pod['metadata']['name'] + ' Ready')
        for container in pod['spec']['containers']:
            resources = container.get('resources', {})
            require(bool(resources.get('requests', {}).get('memory')) and bool(resources.get('limits', {}).get('memory')), pod['metadata']['name'] + '/' + container['name'] + ' has memory request and limit')
    dashboard = kubectl(args.ssh_host, 'get', '--raw', f'/api/v1/namespaces/{NAMESPACE}/services/http:kube-prometheus-stack-grafana:80/proxy/api/dashboards/uid/socrat-overview')
    require(dashboard.get('dashboard', {}).get('uid') == 'socrat-overview', 'Socrat Overview dashboard provisioned in Grafana')
    url = args.grafana_url.rstrip('/') + '/api/search'
    require(public_status(url) == 401, 'public Grafana denies anonymous access')
    secret = kubectl(args.ssh_host, '-n', NAMESPACE, 'get', 'secret', 'socrat-grafana-admin', '-o', 'json')['data']
    credentials = ':'.join(base64.b64decode(secret[key]).decode() for key in ['admin-user', 'admin-password'])
    require(public_status(url, credentials) == 200, 'authenticated public Grafana API works')
    timestamp = int(time.time()) - 60
    snapshot = {
        'timestamp': timestamp,
        'samples': query(args.ssh_host, 'node_uname_info', timestamp),
        'pvc_uids': {pvc['metadata']['name']: pvc['metadata']['uid'] for pvc in pvcs},
    }
    if args.snapshot:
        require(bool(snapshot['samples']), 'historical samples available for persistence baseline')
        args.snapshot.write_text(json.dumps(snapshot, indent=2) + '\n')
        print('Persistence baseline saved:', args.snapshot)
    if args.compare:
        baseline = json.loads(args.compare.read_text())
        require(snapshot['pvc_uids'] == baseline['pvc_uids'], 'PVC identities unchanged after controlled restart')
        saved = sorted(baseline['samples'], key=lambda item: json.dumps(item['metric'], sort_keys=True))
        current = sorted(query(args.ssh_host, 'node_uname_info', baseline['timestamp']), key=lambda item: json.dumps(item['metric'], sort_keys=True))
        require(bool(saved) and current == saved, 'historical Prometheus samples survived controlled restart')


if __name__ == '__main__':
    main()
