import argparse
import json
import shlex
import subprocess
import time
import urllib.parse
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


def remote_http_status(host, url, resolve_address=None, forwarded_for=None, interface=None,
                       public_absence=False):
    command = ['curl', '--silent', '--show-error', '--noproxy', '*',
               '--connect-timeout', '10', '--max-time', '30',
               '--write-out', '\n%{http_code}']
    if public_absence:
        command += ['--insecure']
    else:
        command += ['--output', '/dev/null']
    if resolve_address:
        parsed = urllib.parse.urlsplit(url)
        command += ['--resolve', f'{parsed.hostname}:{parsed.port or 443}:{resolve_address}']
    if interface:
        command += ['--interface', interface]
    if forwarded_for:
        command += ['--header', f'X-Forwarded-For: {forwarded_for}']
    command.append(url)
    result = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', host, shlex.join(command)],
        capture_output=True, text=True, timeout=45,
    )
    if result.returncode:
        raise RuntimeError('HTTP probe failed: ' + result.stderr[-1000:])
    body, _, status = result.stdout.rpartition("\n")
    if public_absence:
        require(body.strip() == "404 page not found",
                "public HTTPS returns only the ingress default 404 body")
    return int(status)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-host', default='socrat-0')
    parser.add_argument('--grafana-url', default='https://grafana.socrat.alchemmist.xyz')
    parser.add_argument('--external-ssh-host', default='socrat-2-direct')
    parser.add_argument('--grafana-private-address', default='10.250.0.3')
    parser.add_argument('--grafana-private-source', default='10.250.0.1')
    parser.add_argument('--grafana-public-address', default='109.173.40.247')
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
    require(dashboard.get('dashboard', {}).get('title') == 'Overview', 'Overview dashboard provisioned in Grafana')
    health = next(panel for panel in dashboard['dashboard']['panels'] if panel['id'] == 5)
    require(health['type'] == 'stat' and 'ALERTS{' in health['targets'][0]['expr']
            and 'KubePodNotReady' in health['targets'][0]['expr']
            and health['options']['colorMode'] == 'background_solid',
            'Cluster health shows alert counts in colored cards')
    rules = kubectl(args.ssh_host, 'get', '--raw', f'/api/v1/namespaces/{NAMESPACE}/services/http:kube-prometheus-stack-grafana:80/proxy/api/prometheus/prometheus/api/v1/rules')
    require(rules.get('status') == 'success', 'Grafana can read Prometheus alert rules')
    alert_rules = {rule['name']: rule for group in rules['data']['groups'] for rule in group['rules'] if rule.get('type') == 'alerting'}
    for name, resource in [('KubePodNotReady', 'pod'), ('KubePodCrashLooping', 'pod'),
                           ('KubeNodeNotReady', 'node'), ('KubeNodeUnreachable', 'node')]:
        url = alert_rules[name].get('annotations', {}).get('rancher_url', '')
        suffix = '{{ $labels.namespace }}/{{ $labels.pod }}' if resource == 'pod' else '{{ $labels.node }}'
        require(url == f'https://rancher.socrat.alchemmist.xyz/dashboard/c/local/explorer/{resource}/' + suffix,
                f'{name} links to its Rancher resource')
    for name in ['KubePodNotReady', 'KubeNodeNotReady']:
        require('becomes Firing after' in alert_rules[name]['annotations']['description'],
                f'{name} description is accurate during Pending')
    for name in ['KubeMemoryOvercommit', 'KubeCPUOvercommit']:
        require(alert_rules[name]['annotations'].get('rancher_url') == 'https://rancher.socrat.alchemmist.xyz/dashboard/c/local/explorer',
                f'{name} links to the Rancher cluster')
    catalog = kubectl(args.ssh_host, 'get', '--raw', f'/api/v1/namespaces/{NAMESPACE}/services/http:kube-prometheus-stack-grafana:80/proxy/api/search?limit=1000')
    dashboards = [item for item in catalog if item.get('type') == 'dash-db']
    primary = {item['uid']: item['title'] for item in dashboards if not item.get('folderUid')}
    require(primary == {'socrat-overview': 'Overview', 'socrat-nodes': 'Nodes', 'socrat-services': 'Services', 'socrat-llm': 'LLM'}, 'Only the four primary dashboards appear at the root')
    embedded = [item for item in dashboards if item.get('folderTitle') == 'Rancher']
    require(len(embedded) == 12 and all(not item['title'].startswith(('[Rancher] ', 'Rancher / ')) for item in embedded), 'Embedded Rancher dashboards are grouped without title prefixes')
    require(len(dashboards) == 16 and all(not item.get('folderUid') or item.get('folderTitle') == 'Rancher' for item in dashboards), 'Only primary and embedded Rancher dashboards are installed')
    for uid in ['rancher-node-1', 'rancher-node-detail-1']:
        node_dashboard = kubectl(args.ssh_host, 'get', '--raw', f'/api/v1/namespaces/{NAMESPACE}/services/http:kube-prometheus-stack-grafana:80/proxy/api/dashboards/uid/{uid}')['dashboard']
        resolver = next(v for v in node_dashboard['templating']['list'] if v['name'] == 'exporter_instance')
        expression = resolver['definition'].removeprefix('query_result(')[:-1]
        cpu = next(t['expr'] for p in node_dashboard['panels'] if p.get('title') == 'CPU Utilization' for t in p['targets'])
        for node in nodes:
            name = node['metadata']['name']
            address = next(a['address'] for a in node['status']['addresses'] if a['type'] == 'InternalIP')
            resolved = query(args.ssh_host, expression.replace('$instance', address + ':9796'))
            require(len(resolved) == 1 and resolved[0]['metric'].get('nodename') == name, f'{uid} resolves Rancher instance for {name}')
            actual = resolved[0]['metric']['instance']
            require(bool(query(args.ssh_host, cpu.replace('$exporter_instance', actual).replace('$__rate_interval', '2m'))), f'{uid} CPU query returns data for {name}')

    url = args.grafana_url.rstrip('/') + '/api/search'
    require(remote_http_status(args.ssh_host, url, args.grafana_private_address,
                               interface=args.grafana_private_source) == 200,
            'WireGuard Grafana API works without credentials')
    hostname = urllib.parse.urlsplit(args.grafana_url).hostname
    ingresses = kubectl(args.ssh_host, 'get', 'ingress', '-A', '-o', 'json')['items']
    for ingress in ingresses:
        for rule in ingress.get('spec', {}).get('rules', []):
            if rule.get('host') != hostname:
                continue
            paths = rule.get('http', {}).get('paths', [])
            labels = ingress['metadata'].get('labels', {})
            solver = labels.get('acme.cert-manager.io/http01-solver') == 'true'
            require(solver and bool(paths) and all(
                path.get('path', '').startswith('/.well-known/acme-challenge/')
                for path in paths),
                'no permanent public Grafana Ingress: ' + ingress['metadata']['name'])
    print('PASS: no permanent public Grafana Ingress exists')
    require(remote_http_status(args.ssh_host, url, args.grafana_public_address,
                               public_absence=True) == 404,
            'home LAN public address has no Grafana route')
    for forwarded_for in [None, '10.250.0.4', '192.168.0.24']:
        require(remote_http_status(args.external_ssh_host, url, args.grafana_public_address,
                                   forwarded_for=forwarded_for, public_absence=True) == 404,
                'external public address has no Grafana route' +
                (f' with spoofed X-Forwarded-For: {forwarded_for}' if forwarded_for else ''))
    search = kubectl(args.ssh_host, 'get', '--raw',
                     f'/api/v1/namespaces/{NAMESPACE}/services/http:kube-prometheus-stack-grafana:80/proxy/api/search')
    require(isinstance(search, list) and any(item.get('uid') == 'socrat-overview' for item in search),
            'internal anonymous Grafana Viewer can find Overview')
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
