"""Fenced native Open WebUI HTTP-only SDK rollout after source/renewal proofs.

No DB/model/image/auth/metrics-owner changes, no concurrent SQLite replicas.
Keeps Recreate strategy and extends graceful request drain; never force kills.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('bootstrap', ROOT / 'scripts/otel-production-bootstrap.py')
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)
ENDPOINT = 'https://10.250.0.3:44318/v1/traces'


def source_data():
    return {'source_privacy.py': (ROOT / 'scripts/otel-sdk-source-privacy.py').read_text(),
            'open_webui_source_profile.py': (ROOT / 'scripts/otel-open-webui-source-profile.py').read_text(),
            'sitecustomize.py': (ROOT / 'deploy/monitoring/otel/open-webui-sitecustomize.py').read_text()}


def source_configmap_name():
    return 'open-webui-otel-source-' + hashlib.sha256(json.dumps(source_data(), sort_keys=True).encode()).hexdigest()[:16]


def sdk_environment():
    return {'PYTHONPATH': '/etc/otel-source:/app/backend', 'PYTHONDONTWRITEBYTECODE': '1',
            'ENABLE_OTEL': 'true', 'ENABLE_OTEL_TRACES': 'true', 'ENABLE_OTEL_METRICS': 'false', 'ENABLE_OTEL_LOGS': 'false',
            'OTEL_OTLP_SPAN_EXPORTER': 'http', 'OTEL_EXPORTER_OTLP_PROTOCOL': 'http/protobuf',
            'OTEL_EXPORTER_OTLP_TRACES_PROTOCOL': 'http/protobuf', 'OTEL_EXPORTER_OTLP_ENDPOINT': ENDPOINT,
            'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT': ENDPOINT, 'OTEL_EXPORTER_OTLP_INSECURE': 'false',
            'OTEL_EXPORTER_OTLP_CERTIFICATE': '/etc/otel-client/ca.crt',
            'OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE': '/etc/otel-client/tls.crt',
            'OTEL_EXPORTER_OTLP_CLIENT_KEY': '/etc/otel-client/tls.key', 'OTEL_EXPORTER_OTLP_HEADERS': 'Connection=close',
            'OTEL_BASIC_AUTH_USERNAME': '', 'OTEL_BASIC_AUTH_PASSWORD': '',
            'OTEL_SERVICE_NAME': 'open-webui', 'OTEL_TRACES_SAMPLER': 'always_on',
            'OTEL_METRICS_EXPORTER': 'none', 'OTEL_LOGS_EXPORTER': 'none',
            'OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST': '',
            'OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE': '',
            'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT': 'NO_CONTENT',
            'UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN': '7200'}


def environment_matches(entry, name, value):
    # Kubernetes omits explicit empty EnvVar.value in its API representation.
    # Accept only that exact canonical default, never valueFrom or other fields.
    return entry == {'name': name, 'value': value} or (value == '' and entry == {'name': name})


def run(output, apply):
    os.umask(0o077)
    controller = Path.home() / 'Library/Application Support/homelab/otel-controller'
    if not output.resolve().is_relative_to(controller.resolve()):
        raise ValueError('Private preimages must remain in durable controller root')
    evidence = ROOT / 'deploy/monitoring/migration-evidence'
    bootstrap = json.loads((evidence / 'open-webui-sdk-early-bootstrap-20261101.json').read_text())
    renewal = json.loads((evidence / 'open-webui-sdk-leaf-renewal-20261101.json').read_text())
    if not (bootstrap['sourceConfigMapData'] == source_data() and bootstrap['source']['success']
            and bootstrap['source']['earlyBootstrapRequiredWithoutManualFallback'] and bootstrap['backend']['success']
            and renewal['source']['success'] and renewal['source']['sameNativeProviderAndExporterInstance']
            and renewal['source']['sdkLeafReloadVerified'] and renewal['rotation']['clientKeypairRotationVerified']
            and len(renewal['backend']) == 2 and all(x['success'] for x in renewal['backend'])
            and all(bootstrap['source']['unsafeAndDuplicateInstrumentorsDisabled'].values())):
        raise ValueError('Exact source/profile/bootstrap/renewal/backend gates must pass before enablement')
    kube = BOOTSTRAP.kube
    deployment = kube('-n', 'llm', 'get', 'deployment', 'open-webui', '-o', 'json')
    template = deployment['spec']['template']; pod = template['spec']
    container = next(c for c in pod['containers'] if c['name'] == 'open-webui')
    if container['image'].split('@')[-1] != bootstrap['testedImage'].split('@')[-1]:
        raise ValueError('Production image differs from tested pinned runtime')
    if deployment['spec'].get('replicas', 1) != 1 or deployment['spec'].get('strategy', {}).get('type') != 'Recreate' or deployment.get('status', {}).get('availableReplicas') != 1:
        raise ValueError('Require healthy single SQLite-safe Recreate deployment')
    current = {e['name']: e for e in container.get('env', [])}
    for name, value in sdk_environment().items():
        if name in current and not environment_matches(current[name], name, value):
            raise ValueError('Unreviewed conflicting SDK/drain environment')
    cm_name = source_configmap_name()
    volumes = [{'name': 'otel-source', 'configMap': {'name': cm_name, 'defaultMode': 420}},
               {'name': 'otel-client', 'secret': {'secretName': 'otel-app-tls-open-webui', 'defaultMode': 256}}]
    mounts = [{'name': 'otel-source', 'mountPath': '/etc/otel-source', 'readOnly': True},
              {'name': 'otel-client', 'mountPath': '/etc/otel-client', 'readOnly': True}]
    for desired, existing in [(volumes, pod.get('volumes', [])), (mounts, container.get('volumeMounts', []))]:
        if any(any(old['name'] == item['name'] and old != item for old in existing) for item in desired):
            raise ValueError('Conflicting credential/bootstrap volume or mount')
    fingerprint = hashlib.sha256(json.dumps({'env': sdk_environment(), 'source': source_data()}, sort_keys=True).encode()).hexdigest()
    output.mkdir(mode=0o700)
    (output / 'deployment-before-private.json').write_text(json.dumps(deployment, indent=2))
    receipt = {'applied': False, 'configurationSHA256': fingerprint, 'sourceConfigMap': cm_name,
               'modelDatabaseImageAuthAndMetricsOwnershipChanged': False, 'oldPodsForceKilled': False,
               'concurrentSqliteReplicasCreated': False, 'productionSdkCoverageVerified': False}
    def record():
        (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    record()
    if not apply:
        print(json.dumps(receipt)); return
    cm = kube('-n', 'llm', 'get', 'configmap', cm_name, '--ignore-not-found', '-o', 'json')
    if cm:
        if cm.get('data') != source_data() or not cm.get('immutable'):
            raise ValueError('Immutable source bootstrap mismatch')
    else:
        kube('create', '-f', '-', '-o', 'json', document={'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
             'metadata': {'namespace': 'llm', 'name': cm_name}, 'data': source_data()})
    if (template.get('metadata', {}).get('annotations', {}).get('homelab.alchemmist.xyz/sdk-configuration-sha256') == fingerprint
        and all(environment_matches(current.get(name), name, value) for name, value in sdk_environment().items())
        and all(entry in pod.get('volumes', []) for entry in volumes) and all(entry in container.get('volumeMounts', []) for entry in mounts)
        and pod.get('terminationGracePeriodSeconds', 0) >= 7200):
        receipt.update(alreadyReconciled=True, newSdkPodReady=True); record(); print(json.dumps(receipt)); return
    patch = {'metadata': {'resourceVersion': deployment['metadata']['resourceVersion']}, 'spec': {'template': {
        'metadata': {'annotations': {'homelab.alchemmist.xyz/sdk-configuration-sha256': fingerprint}}, 'spec': {
            'terminationGracePeriodSeconds': max(7200, pod.get('terminationGracePeriodSeconds', 30)), 'volumes': volumes,
            'containers': [{'name': 'open-webui', 'env': [{'name': k, 'value': v} for k, v in sdk_environment().items()], 'volumeMounts': mounts}]}}}}
    kube('-n', 'llm', 'patch', 'deployment', 'open-webui', '--type=strategic', '-p', json.dumps(patch), '--dry-run=server', '-o', 'json')
    kube('-n', 'llm', 'patch', 'deployment', 'open-webui', '--type=strategic', '-p', json.dumps(patch), '-o', 'json')
    receipt['applied'] = True; record()
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        live = kube('-n', 'llm', 'get', 'deployment', 'open-webui', '-o', 'json')
        pods = kube('-n', 'llm', 'get', 'pods', '-l', 'app=open-webui', '-o', 'json')['items']
        matching = [p for p in pods if p['metadata'].get('annotations', {}).get('homelab.alchemmist.xyz/sdk-configuration-sha256') == fingerprint
                    and any(c['type'] == 'Ready' and c['status'] == 'True' for c in p.get('status', {}).get('conditions', []))]
        if live.get('status', {}).get('observedGeneration', 0) >= live['metadata']['generation'] and matching:
            receipt.update(newSdkPodReady=True, sdkPods=[p['metadata']['name'] for p in matching]); record(); print(json.dumps(receipt)); return
        time.sleep(5)
    raise ValueError('Readiness or natural request drain pending; preserve preimages, never force kill or automatically delete/restore DB')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(args.output, args.apply)
