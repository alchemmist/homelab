"""Minimal, fenced native LiteLLM SDK rollout after isolated proxy privacy gates.

Preserves all model/database/GPU settings and the existing Prometheus callback.
Only ConfigMap callback/privacy fields and Deployment SDK env/leaf mounts change.
Private preimages/receipts stay outside the repository. Never kills draining pods.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('otel_bootstrap', ROOT / 'scripts/otel-production-bootstrap.py')
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)


def sdk_environment():
    return {'OTEL_EXPORTER_OTLP_PROTOCOL': 'http/protobuf',
            'OTEL_EXPORTER_OTLP_ENDPOINT': 'https://10.250.0.3:44318',
            'OTEL_EXPORTER_OTLP_CERTIFICATE': '/etc/otel-client/ca.crt',
            'OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE': '/etc/otel-client/tls.crt',
            'OTEL_EXPORTER_OTLP_CLIENT_KEY': '/etc/otel-client/tls.key',
            'OTEL_EXPORTER_OTLP_INSECURE': 'false',
            'OTEL_EXPORTER_OTLP_HEADERS': 'Connection=close',
            'OTEL_SERVICE_NAME': 'litellm', 'OTEL_TRACES_SAMPLER': 'always_on',
            'OTEL_METRICS_EXPORTER': 'none', 'OTEL_LOGS_EXPORTER': 'none',
            'LITELLM_OTEL_INTEGRATION_ENABLE_METRICS': 'false',
            'LITELLM_OTEL_INTEGRATION_ENABLE_EVENTS': 'false',
            'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT': 'NO_CONTENT'}


def configuration(original):
    result = copy.deepcopy(original)
    settings = result.setdefault('litellm_settings', {})
    callbacks = settings.get('callbacks', [])
    if not isinstance(callbacks, list) or 'prometheus' not in callbacks:
        raise ValueError('Existing authenticated Prometheus callback must be preserved')
    if 'otel' not in callbacks:
        callbacks.append('otel')
    settings['turn_off_message_logging'] = True
    return result


def run(output, apply):
    os.umask(0o077)
    parent = Path.home() / 'Library/Application Support/homelab/otel-controller'
    if not output.resolve().is_relative_to(parent.resolve()):
        raise ValueError('Private rollout evidence must remain in the durable controller root')
    proxy = json.loads((ROOT / 'deploy/monitoring/migration-evidence/litellm-proxy-sdk-canary-20261101.json').read_text())
    if not (proxy['source']['success'] and proxy['source']['httpStatus'] == 200 and proxy['source']['sourcePrivacyAudit']['endedSpans'] >= 2 and not proxy['source']['sourcePrivacyAudit']['sensitiveSyntheticContentFoundAtSource'] and proxy['backend']['success']):
        raise ValueError('Native proxy route, internal child and source privacy gates must pass')
    scope = json.loads((ROOT / 'deploy/monitoring/otel-application-scope.json').read_text())
    if apply and 'litellm' not in scope.get('dedicatedClientCertificates', {}).get('sdkReloadVerifiedForApplications', []):
        raise ValueError('Production apply blocked until least-privilege renewable SDK credential reload is independently verified')
    if apply:
        renewal = json.loads((ROOT / 'deploy/monitoring/migration-evidence/litellm-sdk-leaf-renewal-20261101.json').read_text())
        if not (renewal['source']['success'] and renewal['source']['sameNativeSdkProviderAndExporterInstance']
                and renewal['source']['connectionCloseEnabled'] and renewal['source']['oldAndNewLeafLoadedByNativeTlsStack']
                and renewal['rotation']['clientKeypairRotationVerified'] and len(renewal['backend']) == 2
                and all(proof['success'] for proof in renewal['backend'])):
            raise ValueError('Native same-instance SDK renewal and both backend traces must be independently verified')
    output.mkdir(mode=0o700)
    kube = BOOTSTRAP.kube
    deployment = kube('-n', 'llm', 'get', 'deployment', 'litellm', '-o', 'json')
    configmap = kube('-n', 'llm', 'get', 'configmap', 'litellm-config', '-o', 'json')
    (output / 'deployment-before-private.json').write_text(json.dumps(deployment))
    (output / 'configmap-before-private.json').write_text(json.dumps(configmap))
    original = yaml.safe_load(configmap['data']['config.yaml'])
    changed = configuration(original)
    content = yaml.safe_dump(changed, sort_keys=False)
    pod = deployment['spec']['template']['spec']
    container = next(value for value in pod['containers'] if value['name'] == 'litellm')
    current = {entry['name']: entry for entry in container.get('env', [])}
    for name, value in sdk_environment().items():
        if name in current and current[name] != {'name': name, 'value': value}:
            raise ValueError('Unreviewed conflicting SDK environment; refuse overwrite')
    volume = {'name': 'otel-client', 'secret': {'secretName': 'otel-app-tls-litellm', 'defaultMode': 256}}
    mount = {'name': 'otel-client', 'mountPath': '/etc/otel-client', 'readOnly': True}
    for existing in pod.get('volumes', []):
        if existing['name'] == 'otel-client' and existing != volume:
            raise ValueError('Unexpected existing credential volume')
    for existing in container.get('volumeMounts', []):
        if existing['name'] == 'otel-client' and existing != mount:
            raise ValueError('Unexpected existing credential mount')
    fingerprint = hashlib.sha256(json.dumps({'sdk': sdk_environment(), 'config': changed}, sort_keys=True).encode()).hexdigest()
    deployment_patch = {'metadata': {'resourceVersion': deployment['metadata']['resourceVersion']},
        'spec': {'template': {'metadata': {'annotations': {'homelab.alchemmist.xyz/sdk-configuration-sha256': fingerprint}},
            'spec': {'volumes': [volume], 'containers': [{'name': 'litellm',
                'env': [{'name': name, 'value': value} for name, value in sdk_environment().items()], 'volumeMounts': [mount]}]}}}}
    receipt = {'applied': False, 'productionSdkCoverageVerified': False, 'modelDatabaseAndGpuConfigurationChanged': False,
               'existingPrometheusCallbackPreserved': True, 'sdkMetricsAndLogsExportersEnabled': False,
               'sourceMessageLoggingDisabled': True, 'configurationSHA256': fingerprint, 'drainingPodsForceKilled': False}
    if apply:
        updated = kube('-n', 'llm', 'patch', 'configmap', 'litellm-config', '--type=json', '-p', json.dumps([
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': configmap['metadata']['resourceVersion']},
            {'op': 'replace', 'path': '/data/config.yaml', 'value': content}]), '-o', 'json')
        try:
            kube('-n', 'llm', 'patch', 'deployment', 'litellm', '--type=strategic', '-p', json.dumps(deployment_patch), '-o', 'json')
        except Exception:
            # Restore only our own ConfigMap revision; never clobber another writer.
            kube('-n', 'llm', 'patch', 'configmap', 'litellm-config', '--type=json', '-p', json.dumps([
                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': updated['metadata']['resourceVersion']},
                {'op': 'replace', 'path': '/data/config.yaml', 'value': configmap['data']['config.yaml']}]), '-o', 'json')
            raise
        receipt['applied'] = True
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            live = kube('-n', 'llm', 'get', 'deployment', 'litellm', '-o', 'json')
            state = live.get('status', {})
            if state.get('observedGeneration', 0) >= live['metadata']['generation'] and state.get('updatedReplicas', 0) >= 1 and state.get('availableReplicas', 0) >= 1:
                pods = kube('-n', 'llm', 'get', 'pods', '-l', 'app.kubernetes.io/instance=litellm', '-o', 'json')['items']
                matching = [p for p in pods if p['metadata'].get('annotations', {}).get('homelab.alchemmist.xyz/sdk-configuration-sha256') == fingerprint and any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in p.get('status', {}).get('conditions', []))]
                if matching:
                    receipt.update(newSdkPodReady=True, sdkPods=[p['metadata']['name'] for p in matching],
                                   oldReplicaDrainPending=state.get('replicas', 0) > state.get('updatedReplicas', 0))
                    break
            time.sleep(3)
        else:
            receipt['newSdkPodReady'] = False
        (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if not receipt.get('newSdkPodReady'):
            raise ValueError('SDK candidate did not become ready; private preimages retained; never force kill')
    else:
        (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(args.output, args.apply)
