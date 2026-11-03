"""Provision dedicated native application client leaves, not application rollout.

Never reads any Secret/private key. Narrow reader cannot issue certs or read the
CA, host leaves or any unrelated Secret. Certificate mirroring/reload is a
separate maintained lifecycle gate before SDK rollout.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('application_bootstrap', ROOT / 'scripts/otel-production-bootstrap.py')
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)
NS = 'cattle-monitoring-system'
SA = 'otel-application-credentials'
APPS = ['harbor', 'litellm', 'vllm', 'open-webui', 'lms']


def resources():
    labels = {'app.kubernetes.io/part-of': 'homelab-otel', 'homelab-otel-role': 'application-client'}
    objects = []
    for app in APPS:
        name = 'otel-app-tls-' + app
        objects.append({'apiVersion': 'cert-manager.io/v1', 'kind': 'Certificate',
                        'metadata': {'name': name, 'namespace': NS, 'labels': labels},
                        'spec': {'secretName': name, 'commonName': 'otel-app-' + app,
                                 'duration': '2160h', 'renewBefore': '720h',
                                 'privateKey': {'algorithm': 'ECDSA', 'size': 256, 'rotationPolicy': 'Always'},
                                 'usages': ['digital signature', 'client auth'],
                                 'issuerRef': {'name': 'otel-ca', 'kind': 'Issuer'}}})
    objects.append({'apiVersion': 'v1', 'kind': 'ServiceAccount',
                    'metadata': {'name': SA, 'namespace': NS, 'labels': labels},
                    'automountServiceAccountToken': False})
    objects.append({'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'Role',
                    'metadata': {'name': SA, 'namespace': NS, 'labels': labels},
                    'rules': [{'apiGroups': [''], 'resources': ['secrets'],
                               'resourceNames': ['otel-app-tls-' + app for app in APPS], 'verbs': ['get']}]})
    objects.append({'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
                    'metadata': {'name': SA, 'namespace': NS, 'labels': labels},
                    'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': SA},
                    'subjects': [{'kind': 'ServiceAccount', 'name': SA, 'namespace': NS}]})
    return objects


def assess(resource, verb, name=None, group='', namespace=NS):
    attributes = {'namespace': namespace, 'verb': verb, 'group': group, 'resource': resource}
    if name is not None:
        attributes['name'] = name
    document = {'apiVersion': 'authorization.k8s.io/v1', 'kind': 'SubjectAccessReview',
                'spec': {'user': 'system:serviceaccount:' + NS + ':' + SA,
                         'groups': ['system:serviceaccounts', 'system:serviceaccounts:' + NS, 'system:authenticated'],
                         'resourceAttributes': attributes}}
    result = BOOTSTRAP.kube('create', '-f', '-', '-o', 'json', document=document)['status']
    if result.get('evaluationError'):
        raise ValueError('RBAC evaluation failed; denial is not certified')
    return result.get('allowed') is True


def run(output):
    os.umask(0o077)
    if output.exists():
        raise ValueError('Preserve existing application PKI observations')
    desired = resources()
    existing = BOOTSTRAP.kube('-n', NS, 'get', 'certificates', '-o', 'json')['items']
    specs = {item['metadata']['name']: item['spec'] for item in existing}
    for item in desired:
        if item['kind'] == 'Certificate' and item['metadata']['name'] in specs:
            actual = specs[item['metadata']['name']]
            if any(actual.get(key) != value for key, value in item['spec'].items()):
                raise ValueError('Existing certificate identity differs; do not overwrite')
    BOOTSTRAP.kube('apply', '-f', '-', '-o', 'json', document={'apiVersion': 'v1', 'kind': 'List', 'items': desired})
    # Existing bootstrap wrapper deliberately suppresses wait stdout, never logs keys.
    BOOTSTRAP.kube('-n', NS, 'wait', '--for=condition=Ready', 'certificate', '-l', 'homelab-otel-role=application-client', '--timeout=60s')
    read_allowed = {app: assess('secrets', 'get', 'otel-app-tls-' + app) for app in APPS}
    forbidden = {'caPrivateKeyRead': assess('secrets', 'get', 'otel-root-ca'),
                 'hostPrivateKeyRead': assess('secrets', 'get', 'otel-tls-socrat-0'),
                 'listAllSecrets': assess('secrets', 'list'),
                 'certificateCreation': assess('certificates', 'create', group='cert-manager.io'),
                 'deploymentPatch': assess('deployments', 'patch', 'litellm', group='apps', namespace='llm')}
    if not all(read_allowed.values()) or any(forbidden.values()):
        raise ValueError('Dedicated application reader is missing or overprivileged')
    observed = BOOTSTRAP.kube('-n', NS, 'get', 'certificates', '-l', 'homelab-otel-role=application-client', '-o', 'json')['items']
    report = {'collectedAt': datetime.now(timezone.utc).isoformat(), 'applicationDeploymentsChanged': False,
              'privateKeysReadByThisTool': False, 'secretValuesSaved': False,
              'dedicatedClientCertificatesReady': len(observed) == len(APPS) and all(any(condition['type'] == 'Ready' and condition['status'] == 'True' for condition in item.get('status', {}).get('conditions', [])) for item in observed),
              'namedClientLeafReadAllowed': read_allowed, 'forbiddenPermissionsAllowed': forbidden,
              'renewalMirrorAndSdkReloadStillRequired': True, 'internalSdkCoverageComplete': False,
              'certificates': [{'name': item['metadata']['name'], 'notBefore': item.get('status', {}).get('notBefore'),
                                'notAfter': item.get('status', {}).get('notAfter'), 'renewalTime': item.get('status', {}).get('renewalTime'),
                                'revision': item.get('status', {}).get('revision')} for item in observed]}
    if report['dedicatedClientCertificatesReady'] is not True:
        raise ValueError('Not all dedicated application leaves are ready')
    with open(output, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({key: report[key] for key in ['dedicatedClientCertificatesReady', 'applicationDeploymentsChanged', 'privateKeysReadByThisTool', 'renewalMirrorAndSdkReloadStillRequired']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
