#!/usr/bin/env python3
"""Read-only, metadata-only logging acceptance. No range/log-stream API calls."""
import argparse
import concurrent.futures
import json
import math
import re
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

SAFE = re.compile(r'[A-Za-z0-9_.@:-]{1,253}')
SEVERITIES = {'trace', 'debug', 'info', 'warn', 'error', 'fatal', 'unknown'}
LABELS = {'k8s_namespace_name', 'audit_pod', 'audit_container', 'host_name', 'service_name', 'severity', 'audit_unit'}
GROUP = ','.join(sorted(LABELS))

def query(selector, window):
    # Extract structured metadata before aggregation, without returning any log lines.
    return ('sum by (' + GROUP + ') (count_over_time(' + selector +
            ' | label_format audit_pod="{{.k8s_pod_name}}", audit_container="{{.k8s_container_name}}", audit_unit="{{.systemd_unit}}" [' + str(window) + 's]))')

def validate(document):
    if document.get('status') != 'success' or document.get('warnings') or document.get('data', {}).get('resultType') != 'vector':
        raise ValueError('Invalid or partial metadata response')
    points = document['data']['result']
    if len(points) > 10000:
        raise ValueError('Series budget exceeded')
    clean = []
    for point in points:
        labels = point['metric']
        if any(k not in LABELS or not isinstance(v, str) or (v and not SAFE.fullmatch(v)) for k, v in labels.items()):
            raise ValueError('Unsafe metadata')
        count = float(point['value'][1])
        if not math.isfinite(count) or count < 0:
            raise ValueError('Invalid count')
        clean.append({'labels': labels, 'count': count})
    return clean

def inventory(pods, workloads, hosts):
    sources = []
    for pod in pods.get('items', []):
        meta, spec = pod['metadata'], pod['spec']
        for kind in ('containers', 'initContainers', 'ephemeralContainers'):
            for container in spec.get(kind, []):
                sources.append({'kind': 'container', 'namespace': meta['namespace'], 'pod': meta['name'],
                                'container': container['name'], 'containerType': kind, 'exists': True,
                                'emission': 'unknown', 'phase': pod.get('status', {}).get('phase', 'Unknown')})
    # Controllers without pods must not disappear from the coverage denominator.
    for obj in workloads.get('items', []):
        sources.append({'kind': 'workload', 'namespace': obj['metadata']['namespace'],
                        'name': obj['metadata']['name'], 'workloadKind': obj['kind'], 'exists': True,
                        'emission': 'unknown'})
    for host in hosts:
        if set(host) - {'host', 'unit', 'exists', 'emission'} or not all(SAFE.fullmatch(host[k]) for k in ('host', 'unit')):
            raise ValueError('Invalid host registry')
        if host.get('emission', 'unknown') not in {'unknown', 'expected', 'silent'}:
            raise ValueError('Invalid emission expectation')
        sources.append(dict(host, kind='host', exists=host.get('exists', None), emission=host.get('emission', 'unknown')))
    return sources

def matches(source, labels):
    if source['kind'] == 'container':
        return all(labels.get(k) == source[v] for k, v in [('k8s_namespace_name', 'namespace'), ('audit_pod', 'pod'), ('audit_container', 'container')])
    if source['kind'] == 'host':
        return labels.get('host_name') == source['host'] and source['unit'] in (labels.get('audit_unit'), labels.get('service_name'))
    return False

def assess(sources, recent, hour):
    rows = []
    for source in sources:
        fresh = [p for p in recent if p['count'] > 0 and matches(source, p['labels'])]
        older = [p for p in hour if p['count'] > 0 and matches(source, p['labels'])]
        canonical = [p for p in fresh if p['labels'].get('service_name') and p['labels'].get('severity') in SEVERITIES]
        row = dict(source, emits=True if fresh else None, fresh=bool(fresh),
                   deliveredInHour=bool(older), canonical=bool(canonical), legacyObserved=bool(fresh) and not bool(canonical))
        row['status'] = ('verified' if canonical and len(canonical) == len(fresh) else 'emits') if fresh else (
            'silent' if source.get('emission') == 'silent' else 'unknown')
        # No logs cannot prove silence, absence, or a broken collector.
        if source['kind'] == 'workload':
            row['status'] = 'exists'
        rows.append(row)
    return rows

def kubectl(resource):
    result = subprocess.run(['kubectl', 'get', resource, '--all-namespaces', '-o', 'json', '--request-timeout=15s'],
                            capture_output=True, timeout=20)
    if result.returncode:
        raise ValueError('Read-only inventory request failed')
    return json.loads(result.stdout)

def fetch(base, context, selector, window):
    url = base + '/loki/api/v1/query?' + urllib.parse.urlencode({'query': query(selector, window)})
    with urllib.request.urlopen(url, context=context, timeout=15) as response:
        body = response.read(8 * 1024 * 1024 + 1)
    if len(body) > 8 * 1024 * 1024:
        raise ValueError('Response budget exceeded')
    return validate(json.loads(body))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hosts', type=Path, required=True, help='Explicit JSON host/unit expectations; [] means none inventoried')
    parser.add_argument('--tls-dir', type=Path, default=Path('/var/lib/homelab-otel/tls'))
    parser.add_argument('--loki', default='https://10.250.0.3:3100')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'https://[A-Za-z0-9.:-]+', args.loki):
        parser.error('Loki must be an HTTPS origin without credentials, path or query')
    try:
        sources = inventory(kubectl('pods'), kubectl('deployments,statefulsets,daemonsets,jobs,cronjobs'), json.loads(args.hosts.read_text()))
        context = ssl.create_default_context(cafile=str(args.tls_dir / 'ca.crt'))
        context.load_cert_chain(str(args.tls_dir / 'client.crt'), str(args.tls_dir / 'client.key'))
        # Exactly four bounded queries, at most two concurrent. No retries.
        jobs = [(selector, seconds) for seconds in (600, 3600) for selector in ('{k8s_namespace_name!=""}', '{host_name!=""}')]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda job: fetch(args.loki, context, *job), jobs))
        rows = assess(sources, results[0] + results[1], results[2] + results[3])
        report = {'observedAtUnix': time.time(), 'freshWindowSeconds': 600, 'historyWindowSeconds': 3600,
                  'logBodiesFetchedOrSaved': False, 'sources': rows,
                  'restartCheck': 'not_run', 'rotationCheck': 'not_run',
                  'fullCoverageAccepted': False, 'hostInventoryComplete': False}
        with args.output.open('x', opener=lambda p, f: __import__('os').open(p, f, 0o600)) as out:
            json.dump(report, out, indent=2)
            out.write('\n')
        print(json.dumps({'sources': len(rows), 'verified': sum(r['status'] == 'verified' for r in rows), 'acceptance': 'manual gates remain'}))
    except Exception:
        # Exception text, HTTP errors and kubectl stderr may contain sensitive data.
        parser.exit(2, 'Coverage check failed; no raw response or credential details emitted.\n')

if __name__ == '__main__':
    main()
