"""Persistent measured 72-hour production health window; never a synthetic soak claim."""
from datetime import datetime, timezone
import json
import hashlib
import os
import re
from pathlib import Path
import ssl
import time
import urllib.parse
import urllib.request

ROOT = Path('/var/lib/homelab-otel-soak')
TLS = Path('/var/lib/homelab-otel/tls')
REQUIRED_SECONDS = 72 * 3600


def get(url, context=None):
    with urllib.request.urlopen(url, context=context, timeout=20) as response:
        return json.load(response)


def query(expression):
    result = get('http://10.43.147.125:9090/api/v1/query?' + urllib.parse.urlencode({'query': expression, 'partial_response': 'false'}))
    if result.get('status') != 'success' or result.get('warnings'):
        raise ValueError('Native Thanos query failed or was partial')
    return result['data']['result']


def effective_sources(points, lookup):
    """Exclude only a vanished/terminating singleton pod with a healthy successor.

    The hourly existing cascade replaces this pod. A fresh failed scrape of the
    deleted pod must not masquerade as a failed current logical source. Every
    other failure, missing replacement, nonterminating live pod or missing proof fails.
    """
    active, retired = [], []
    for point in points:
        metric = point['metric']
        pod = metric.get('pod', '')
        if float(point['value'][1]) == 1 or metric.get('job') != 'cattle-monitoring-system/thanos' or not re.fullmatch(r'thanos-compactor-[a-z0-9]+-[a-z0-9]+', pod):
            active.append(point)
            continue
        replica_set = pod.rsplit('-', 1)[0]
        old_selector = 'kube_pod_info{namespace="cattle-monitoring-system",pod=' + json.dumps(pod) + '}'
        if lookup(old_selector + ' and (time()-timestamp(' + old_selector + ')<20)'):
            deleting = 'kube_pod_deletion_timestamp{namespace="cattle-monitoring-system",pod=' + json.dumps(pod) + '}'
            if not lookup(deleting + '>0 and (time()-timestamp(' + deleting + ')<20)'):
                active.append(point)
                continue
        successor = None
        for other in points:
            labels = other['metric']
            new_pod = labels.get('pod', '')
            if float(other['value'][1]) != 1 or labels.get('job') != metric['job'] or new_pod == pod or new_pod.rsplit('-', 1)[0] != replica_set:
                continue
            owner = 'kube_pod_owner{namespace="cattle-monitoring-system",pod=' + json.dumps(new_pod) + ',owner_kind="ReplicaSet",owner_name=' + json.dumps(replica_set) + ',owner_is_controller="true"}'
            ready = 'kube_pod_status_ready{namespace="cattle-monitoring-system",pod=' + json.dumps(new_pod) + ',condition="true"}'
            desired = 'kube_replicaset_spec_replicas{namespace="cattle-monitoring-system",replicaset=' + json.dumps(replica_set) + '}'
            expression = '(' + owner + '==1 and (time()-timestamp(' + owner + ')<20)) and on(namespace,pod) (' + ready + '==1 and (time()-timestamp(' + ready + ')<20)) and on(namespace) (' + desired + '==1 and (time()-timestamp(' + desired + ')<20))'
            if lookup(expression):
                successor = new_pod
                break
        if successor is None:
            active.append(point)
        else:
            retired.append({'retiredPod': pod, 'healthySuccessorPod': successor, 'replicaSet': replica_set})
    return active, retired


def read_boundary(stores):
    if stores.get('status') != 'success':
        raise ValueError('Native store discovery failed')
    data = stores.get('data', {})
    sidecars = data.get('sidecar', [])
    raw = [item for item in data.get('store', []) if item.get('name', '').split('.')[0] == 'thanos-store']
    if len(raw) != 1 or len(sidecars) != 1 or raw[0].get('lastError') or sidecars[0].get('lastError'):
        raise ValueError('Native raw/sidecar routing is missing or unhealthy')
    end = raw[0]['maxTime']
    start = sidecars[0]['minTime']
    if end < start:
        raise ValueError('Native raw/sidecar read boundary has an uncovered interval')
    return {'rawMaximumTime': end, 'sidecarMinimumTime': start, 'noAdvertisedBoundaryGap': True}


def configuration_sha256():
    digest = hashlib.sha256(Path(__file__).read_bytes())
    epoch = ROOT / 'configuration-epoch.json'
    if epoch.exists():
        digest.update(epoch.read_bytes())
    return digest.hexdigest()


def run():
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, exist_ok=True)
    path = ROOT / 'state.json'
    now = time.time()
    state = json.loads(path.read_text()) if path.exists() else {'startedAt': now, 'requiredSeconds': REQUIRED_SECONDS, 'completed': False, 'checks': 0, 'failedChecks': 0}
    errors = []
    previous = state.get('lastObservedAt')
    configuration = configuration_sha256()
    if previous is not None and not 0 <= now - previous <= 900:
        errors.append('production observation gap; healthy window reset')
    if state.get('configurationSHA256', configuration) != configuration:
        errors.append('soak configuration changed; healthy window reset')
    state['configurationSHA256'] = configuration
    observed = {}
    try:
        credentials = Path('/var/lib/homelab-otel')
        token = json.loads((credentials / 'token.json').read_text())['token']
        settings = json.loads((credentials / 'credentials.json').read_text())
        api_context = ssl.create_default_context(cafile=str(credentials / 'kubernetes-ca.crt'))
        request = urllib.request.Request(settings['apiServer'] + '/apis/monitoring.coreos.com/v1/namespaces/cattle-monitoring-system/prometheuses/kube-prometheus-stack-prometheus', headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, context=api_context, timeout=15) as response:
            owner = json.load(response)['spec']
        observed['nativeOwnershipVerified'] = owner.get('enableOTLPReceiver') is True and owner.get('listenLocal') is True and owner.get('serviceMonitorSelector', {}).get('matchLabels', {}).get('homelab.alchemmist.xyz/scrape-owner') == 'retired-legacy-prometheus'
        if not observed['nativeOwnershipVerified']:
            errors.append('production is not owned by native OTLP')
        observed['historicalReadBoundary'] = read_boundary(get('http://10.43.147.125:9090/api/v1/stores'))
        points = query('up and (time()-timestamp(up)<20)')
        observed['rawFreshSources'] = len(points)
        points, retired = effective_sources(points, query)
        observed['verifiedRetiredDiscoveryTargets'] = retired
        observed['freshSources'] = len(points)
        if len(points) < 78 or any(float(point['value'][1]) != 1 for point in points):
            errors.append('missing, stale or unhealthy native metric sources')
        failed = query('sum(node_systemd_unit_state{name=~"homelab-otel.*",name!="homelab-otel-soak.service",state="failed"})')
        if failed and float(failed[0]['value'][1]) != 0:
            errors.append('managed native service failed')
        context = ssl.create_default_context(cafile=str(TLS / 'ca.crt'))
        context.load_cert_chain(str(TLS / 'client.crt'), str(TLS / 'client.key'))
        for port in [3100, 3200]:
            with urllib.request.urlopen('https://10.250.0.3:' + str(port) + '/ready', context=context, timeout=10) as response:
                if response.status != 200:
                    errors.append('native backend not ready')
        request = urllib.request.Request('https://10.250.0.3:44318/v1/traces', data=b'', headers={'Content-Type': 'application/x-protobuf'}, method='POST')
        with urllib.request.urlopen(request, context=context, timeout=10) as response:
            if response.status != 200:
                raise ValueError('Private client-mTLS native application HTTP trace receiver is not ready')
        observed['applicationHttpClientMtlsReady'] = True
        logs = get('https://10.250.0.3:3100/loki/api/v1/query?' + urllib.parse.urlencode({'query': 'sum by(host_name)(count_over_time({host_name=~"socrat-.*"}[5m]))'}), context)
        hosts = {point['metric'].get('host_name') for point in logs['data']['result'] if float(point['value'][1]) > 0}
        observed['logHosts'] = sorted(hosts)
        if hosts != {'socrat-0', 'socrat-1', 'socrat-2', 'socrat-3'}:
            errors.append('native log heartbeat coverage incomplete')
        traces = get('https://10.250.0.3:3200/api/search?limit=1', context)
        observed['searchableTracePresent'] = bool(traces.get('traces'))
        if not observed['searchableTracePresent']:
            errors.append('native traces unavailable')
    except Exception as error:
        errors.append(type(error).__name__)
    state['checks'] += 1
    state['lastObservedAt'] = now
    state['lastObservation'] = observed
    state['lastErrors'] = errors
    if errors:
        state['failedChecks'] += 1
        state['continuousHealthySince'] = None
    else:
        if state.get('continuousHealthySince') is None:
            state['continuousHealthySince'] = now
    state['measuredHealthySeconds'] = max(0, now - state['continuousHealthySince']) if state.get('continuousHealthySince') else 0
    state['completed'] = not errors and state['measuredHealthySeconds'] >= REQUIRED_SECONDS
    state['notBeforeUTC'] = datetime.fromtimestamp((state.get('continuousHealthySince') or now) + REQUIRED_SECONDS, timezone.utc).isoformat()
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(path)
    with (ROOT / 'observations.jsonl').open('a') as stream:
        stream.write(json.dumps({'observedAt': now, 'errors': errors, **observed}) + '\n')
    print(json.dumps({'completed': state['completed'], 'errors': errors, 'freshSources': observed.get('freshSources'), 'measuredHealthySeconds': state['measuredHealthySeconds']}))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    run()
