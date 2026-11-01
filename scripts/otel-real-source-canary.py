import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
import uuid



NAMESPACE = 'cattle-monitoring-system'
PROMETHEUS = 'kube-prometheus-stack-prometheus'
CERT_ROOT = '/etc/prometheus/certs/'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def kube(*arguments, document=None):
    result = subprocess.run(['kubectl', '-n', NAMESPACE, *arguments],
                            input=json.dumps(document) if document is not None else None,
                            capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('Canary Kubernetes operation failed; response bodies are not logged')
    return result.stdout


def prometheus(endpoint):
    path = '/api/v1/namespaces/' + NAMESPACE + '/services/http:' + PROMETHEUS + ':9090/proxy/api/v1/' + endpoint
    data = json.loads(kube('get', '--raw', path))
    if data.get('status') != 'success':
        raise ValueError('Production read-only Prometheus inventory failed')
    return data['data']


def free_port():
    with socket.socket() as handle:
        handle.bind(('127.0.0.1', 0))
        return handle.getsockname()[1]


def rewrite_assets(value, paths, kubeconfig):
    if isinstance(value, dict):
        result = {key: rewrite_assets(item, paths, kubeconfig) for key, item in value.items()}
        for discovery in result.get('kubernetes_sd_configs', []):
            if discovery.get('api_server') or discovery.get('kubeconfig_file') or discovery.get('authorization'):
                raise ValueError('Unexpected discovery authentication requires explicit review')
            discovery['kubeconfig_file'] = str(kubeconfig)
        return result
    if isinstance(value, list):
        return [rewrite_assets(item, paths, kubeconfig) for item in value]
    return paths.get(value, value) if isinstance(value, str) else value


def expected_targets(targets, pools):
    selected = [target for target in targets['activeTargets'] if target['scrapePool'] in pools]
    if not selected or any(target['health'] != 'up' for target in selected):
        raise ValueError('Selected sources must be healthy before canary collection')
    identities = [fingerprint({**target['labels'], '__name__': 'up'}) for target in selected]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate source target label sets')
    return set(identities)


def cleanup_workspace(workspace):
    if os.geteuid() != 0 or workspace.is_symlink() or workspace.resolve().parent != Path('/var/tmp/otel-real-source-canary'):
        raise ValueError('Cleanup requires an owned private canary workspace')
    manifest = workspace / 'cleanup.json'
    if not manifest.exists():
        return
    name = json.loads(manifest.read_text())['name']
    if not name.startswith('otel-canary-') or len(name) != 24 or not all(c in '0123456789abcdef' for c in name[12:]):
        raise ValueError('Invalid canary cleanup identity')
    failed = False
    try:
        for kind in ['clusterrolebinding', 'clusterrole', 'serviceaccount']:
            try:
                objects = json.loads(kube('get', kind, '-l', 'homelab.alchemmist.xyz/canary=' + name, '-o', 'json'))['items']
                for obj in objects:
                    if obj['metadata']['name'] != name or obj['metadata'].get('labels', {}).get('homelab.alchemmist.xyz/canary') != name:
                        raise ValueError('Unexpected canary ownership')
                    kube('delete', kind, name, '--wait=true', '--timeout=15s')
            except (RuntimeError, subprocess.TimeoutExpired):
                failed = True
    finally:
        directory = workspace / 'credentials'
        if directory.exists():
            if directory.is_symlink():
                raise ValueError('Credential cleanup refuses symlinks')
            for path in directory.iterdir():
                if path.is_symlink() or not path.is_file():
                    raise ValueError('Credential cleanup refuses non-regular files')
                path.unlink()
    if failed:
        raise RuntimeError('Temporary discovery RBAC cleanup incomplete')


def run(args):
    if os.geteuid() != 0:
        raise ValueError('Private host canary staging requires the authorized root controller')
    contract = json.loads((args.bundle / 'contract.json').read_text())
    collected = datetime.fromisoformat(contract['collectedAt'])
    age = (datetime.now(timezone.utc) - collected).total_seconds()
    if age < 0 or age > 900:
        raise ValueError('Scrape inventory is stale or future-dated')
    scrape = json.loads((args.bundle / 'cluster.json').read_text())
    if fingerprint(scrape) != contract['outputSHA256']['cluster']:
        raise ValueError('Scrape bundle fingerprint differs')
    current = prometheus('status/config')['yaml']
    if hashlib.sha256(current.encode()).hexdigest() != contract['sourceYAMLTextSHA256']:
        raise ValueError('Production source configuration changed after translation')
    fs = os.statvfs('/var/lib/rancher/k3s/storage')
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    if fs.f_bavail < max(30 * 2**30 / fs.f_frsize, fs.f_blocks * 0.2) or int(memory['MemAvailable'].split()[0]) * 1024 < 4 * 2**30:
        raise ValueError('Canary resource reserve is insufficient')
    pools = {job['job_name'] for job in scrape['scrape_configs']}
    expected = expected_targets(prometheus('targets'), pools)
    args.workspace.mkdir(mode=0o700, exist_ok=False)
    credentials = args.workspace / 'credentials'
    credentials.mkdir(mode=0o700)
    name = 'otel-canary-' + uuid.uuid4().hex[:12]
    labels = {'homelab.alchemmist.xyz/canary': name}
    (args.workspace / 'cleanup.json').write_text(json.dumps({'name': name}))
    role = {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRole',
            'metadata': {'name': name, 'labels': labels}, 'rules': [
                {'apiGroups': [''], 'resources': ['nodes', 'services', 'endpoints', 'pods', 'namespaces'], 'verbs': ['get', 'list', 'watch']},
                {'apiGroups': ['discovery.k8s.io'], 'resources': ['endpointslices'], 'verbs': ['get', 'list', 'watch']}]}
    binding = {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRoleBinding',
               'metadata': {'name': name, 'labels': labels}, 'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': name},
               'subjects': [{'kind': 'ServiceAccount', 'name': name, 'namespace': NAMESPACE}]}
    sa = {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': name, 'namespace': NAMESPACE, 'labels': labels}}
    created = []
    children = []
    logs = []
    cleanup_succeeded = True
    result = None
    try:
        for resource in [sa, role, binding]:
            kube('create', '-f', '-', document=resource)
            created.append(resource['kind'])
        token = kube('create', 'token', name, '--duration=10m').strip()
        ca = json.loads(kube('get', 'configmap', 'kube-root-ca.crt', '-o', 'json'))['data']['ca.crt']
        (credentials / 'kubernetes-ca.crt').write_text(ca)
        kubeconfig = credentials / 'kubeconfig.yaml'
        kubeconfig.write_text(json.dumps({'apiVersion': 'v1', 'kind': 'Config',
            'clusters': [{'name': 'canary', 'cluster': {'server': 'https://127.0.0.1:6443', 'certificate-authority': str(credentials / 'kubernetes-ca.crt')}}],
            'users': [{'name': 'canary', 'user': {'token': token}}],
            'contexts': [{'name': 'canary', 'context': {'cluster': 'canary', 'user': 'canary'}}], 'current-context': 'canary'}))
        paths = {}
        for index, reference in enumerate(contract['requiredSecretKeys']):
            response = subprocess.run(['kubectl', '-n', reference['namespace'], 'get', 'secret', reference['secret'], '-o', 'json'], capture_output=True, text=True, timeout=30, check=True)
            secret = json.loads(response.stdout)['data']
            path = credentials / ('source-' + str(index))
            path.write_bytes(base64.b64decode(secret[reference['key']], validate=True))
            paths[reference['mountPath']] = str(path)
        pods = json.loads(kube('get', 'pods', '-l', 'app.kubernetes.io/name=prometheus', '-o', 'json'))['items']
        if len(pods) != 1:
            raise ValueError('Exactly one existing production Prometheus pod is required')
        volume = next(v for v in pods[0]['spec']['volumes'] if v['name'] == 'tls-assets')
        certs = {}
        for source in volume['projected']['sources']:
            if set(source) != {'secret'} or source['secret'].get('items'):
                raise ValueError('Unsupported TLS asset projection')
            secret = json.loads(kube('get', 'secret', source['secret']['name'], '-o', 'json'))['data']
            if set(certs) & set(secret):
                raise ValueError('Ambiguous TLS asset projection')
            certs.update(secret)
        for index, asset in enumerate(contract['requiredFileMounts']):
            if asset in paths:
                continue
            if not asset.startswith(CERT_ROOT) or Path(asset).name not in certs:
                raise ValueError('Unresolved file dependency')
            path = credentials / ('ca-' + str(index))
            path.write_bytes(base64.b64decode(certs[Path(asset).name], validate=True))
            paths[asset] = str(path)
        for path in credentials.iterdir():
            path.chmod(0o600)
        translated = rewrite_assets(scrape, paths, kubeconfig)
        (args.workspace / 'scrape.yaml').write_text(json.dumps(translated))
        port = free_port()
        tls = {'cert_file': str(args.tls / 'server.crt'), 'key_file': str(args.tls / 'server.key'),
               'client_ca_file': str(args.tls / 'ca.crt'), 'client_auth_type': 'RequireAndVerifyClientCert'}
        (args.workspace / 'web.yaml').write_text(json.dumps({'tls_server_config': tls}))
        (args.workspace / 'prometheus.yaml').write_text(json.dumps({'global': {'evaluation_interval': '5s'},
            'scrape_configs': [], 'storage': {'tsdb': {'out_of_order_time_window': '30m'}}, 'otlp': {'translation_strategy': 'NoTranslation', 'promote_scope_metadata': False}}))
        environment = {**os.environ, 'OTEL_TLS_DIR': str(args.tls), 'OTEL_STORAGE_DIR': str(args.workspace / 'queues'),
            'OTEL_BIND_IP': '127.0.0.1', 'OTEL_METRICS_ENDPOINT': 'https://127.0.0.1:' + str(port) + '/api/v1/otlp'}
        collector = json.loads(args.config.read_text())
        collector['receivers'] = {'prometheus': {'trim_metric_suffixes': False, 'config': translated}}
        collector['processors'] = {key: collector['processors'][key] for key in ['memory_limiter', 'batch/metrics']}
        collector['exporters'] = {'otlp_http/metrics': collector['exporters']['otlp_http/metrics']}
        collector['extensions'] = {'file_storage': collector['extensions']['file_storage']}
        collector['service'] = {'extensions': ['file_storage'], 'telemetry': {'metrics': {'level': 'none'}},
            'pipelines': {'metrics': {'receivers': ['prometheus'], 'processors': ['memory_limiter', 'batch/metrics'], 'exporters': ['otlp_http/metrics']}}}
        (args.workspace / 'collector.json').write_text(json.dumps(collector))
        commands = [
            ('prometheus', [str(args.prometheus), '--config.file=' + str(args.workspace / 'prometheus.yaml'),
                '--storage.tsdb.path=' + str(args.workspace / 'tsdb'), '--storage.tsdb.retention.time=2h', '--storage.tsdb.retention.size=2GB',
                '--web.listen-address=127.0.0.1:' + str(port), '--web.config.file=' + str(args.workspace / 'web.yaml'), '--web.enable-otlp-receiver']),
            ('collector', [str(args.binary), '--config=' + str(args.workspace / 'collector.json')])]
        for label, command in commands:
            log = (args.workspace / (label + '.log')).open('x')
            logs.append(log)
            children.append(subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT))
        context = ssl.create_default_context(cafile=str(args.tls / 'ca.crt'))
        context.load_cert_chain(str(args.tls / 'client.crt'), str(args.tls / 'client.key'))
        started = time.monotonic()
        consecutive = 0
        observed = {}
        while time.monotonic() - started < 150:
            if any(process.poll() is not None for process in children):
                raise RuntimeError('Canary native service stopped; inspect private logs')
            try:
                expression = urllib.parse.urlencode({'query': 'up'})
                with urllib.request.urlopen('https://127.0.0.1:' + str(port) + '/api/v1/query?' + expression, context=context, timeout=5) as response:
                    vector = json.load(response)['data']['result']
                observed = {fingerprint(point['metric']): point['value'][1] for point in vector}
                age_query = urllib.parse.urlencode({'query': 'time() - timestamp(up)'})
                with urllib.request.urlopen('https://127.0.0.1:' + str(port) + '/api/v1/query?' + age_query, context=context, timeout=5) as response:
                    ages = [float(point['value'][1]) for point in json.load(response)['data']['result']]
                healthy = (set(observed) == expected and all(value == '1' for value in observed.values())
                           and len(ages) == len(expected) and all(0 <= age < 15 for age in ages))
                consecutive = consecutive + 1 if healthy else 0
                if consecutive >= 3:
                    break
            except (OSError, ValueError, KeyError):
                consecutive = 0
            time.sleep(5)
        if consecutive < 3:
            (args.workspace / 'failure-summary.json').write_text(json.dumps({'expectedTargets': len(expected), 'observedTargets': len(observed), 'matchingTargetLabelSets': len(set(observed) & expected), 'upValues': {value: list(observed.values()).count(value) for value in set(observed.values())}}))
            raise RuntimeError('Real-source target labels, authorization or availability differ; raw responses are not logged')
        collector_log = (args.workspace / 'collector.log').read_text()
        rejected = {key: collector_log.count(marker) for key, marker in {
            'droppedExportBatches': 'Exporting failed. Dropping data.', 'memoryRefusals': 'Refusing data.',
            'failedScrapeCommits': 'Scrape commit failed'}.items()}
        if any(rejected.values()):
            (args.workspace / 'failure-summary.json').write_text(json.dumps(rejected))
            raise RuntimeError('Source canary observed refused or dropped data; capacity is not accepted')
        cgroup = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        cgroup_path = Path('/sys/fs/cgroup') / cgroup.lstrip('/')
        memory_peak = int((cgroup_path / 'memory.peak').read_text())
        memory_max = int((cgroup_path / 'memory.max').read_text())
        result = {'schemaVersion': 1, 'observedAt': datetime.now(timezone.utc).isoformat(), 'scope': 'real cluster metrics only; independent host sources excluded',
            'productionModified': False, 'temporaryDiscoveryRBACCreated': True, 'productionDeployed': False,
            'expectedTargetCount': len(expected), 'healthyTargetCount': len(observed), 'upTargetLabelSetsEquivalent': True,
            'authFileReferenceCountVerified': len(contract['requiredSecretKeys']), 'discoveryUsesDedicatedShortLivedServiceAccount': True,
            'elapsedSeconds': round(time.monotonic() - started, 3), 'privateLoopbackAuthenticatedTLS': True,
            'outOfOrderWindow': '30m', 'rejections': rejected,
            'maximumUpAgeSeconds': round(max(ages), 3), 'aggregateCgroupMemoryPeakBytes': memory_peak,
            'aggregateCgroupMemoryLimitBytes': memory_max,
            'pipeline': 'native prometheusreceiver -> native OTLP exporter -> native Prometheus OTLP receiver',
            'credentialValuesIncludedInReport': False, 'allMetricFamiliesAndRulesVerified': False, 'readyForCutover': False}
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for log in logs:
            log.close()
        for kind in reversed(created):
            try:
                kube('delete', kind.lower(), name, '--wait=true', '--timeout=15s')
            except (RuntimeError, subprocess.TimeoutExpired):
                cleanup_succeeded = False
        for path in credentials.iterdir():
            path.unlink()
    if not cleanup_succeeded:
        raise RuntimeError('Temporary canary RBAC cleanup failed; inspect the retained private run')
    result['temporaryCredentialsRemoved'] = True
    result['temporaryRBACRemoved'] = True
    (args.workspace / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser()
    names = ['binary', 'prometheus', 'config', 'bundle', 'tls', 'workspace']
    for name in names:
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--cleanup-workspace', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.cleanup_workspace:
            cleanup_workspace(args.cleanup_workspace)
            return
        if any(getattr(args, name) is None for name in names):
            raise ValueError('Explicit canary artifacts are required')
        print(json.dumps(run(args), indent=2))
    except Exception:
        raise SystemExit('Real-source canary failed; sensitive responses are not printed. Inspect the private root-owned run artifacts.')


if __name__ == '__main__':
    main()
