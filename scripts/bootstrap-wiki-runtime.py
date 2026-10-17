import argparse
import base64
import json
import secrets
import shlex
import subprocess


class BootstrapError(Exception):
    pass


class Kubernetes:
    def __init__(self, command):
        self.command = command

    def run(self, *args, payload=None):
        result = subprocess.run(self.command + list(args), input=json.dumps(payload) if payload else None, capture_output=True, text=True)
        if result.returncode:
            raise BootstrapError('kubectl failed; inspect resource permissions and availability without logging secret payloads')
        return result.stdout

    def get(self, kind, name, namespace):
        value = self.run('-n', namespace, 'get', kind, name, '--ignore-not-found', '-o', 'json')
        return json.loads(value) if value.strip() else None

    def create(self, resource):
        self.run('create', '-f', '-', payload=resource)


def encoded(value):
    return base64.b64encode(value.encode()).decode()


def decoded(value):
    try:
        return base64.b64decode(value, validate=True).decode()
    except (ValueError, UnicodeError, TypeError):
        raise BootstrapError('Invalid encoded credential in source Secret') from None


def resource(kind, name, namespace, **fields):
    return {'apiVersion': 'v1', 'kind': kind, 'metadata': {'name': name, 'namespace': namespace}, **fields}


def required_data(item, key):
    value = (item or {}).get('data', {}).get(key)
    if not isinstance(value, str) or not value:
        raise BootstrapError('Required credential/configuration field is missing')
    return value


def prerequisites(kube):
    cluster = kube.get('clusters.fleet.cattle.io', 'local', 'fleet-local')
    agent_namespace = (cluster or {}).get('spec', {}).get('agentNamespace')
    if not agent_namespace:
        raise BootstrapError('Cannot discover the local Fleet agent namespace')
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'wiki'}}
    account = resource('ServiceAccount', 'wiki-deployer', agent_namespace)
    role = resource('Role', 'wiki-deployer', 'wiki', rules=[
        {'apiGroups': [''], 'resources': ['secrets', 'configmaps', 'services', 'persistentvolumeclaims'], 'verbs': ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete']},
        {'apiGroups': [''], 'resources': ['pods', 'events'], 'verbs': ['get', 'list', 'watch']},
        {'apiGroups': ['apps'], 'resources': ['deployments', 'replicasets'], 'verbs': ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete']},
        {'apiGroups': ['networking.k8s.io'], 'resources': ['ingresses', 'networkpolicies'], 'verbs': ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete']},
        {'apiGroups': ['policy'], 'resources': ['poddisruptionbudgets'], 'verbs': ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete']},
    ])
    binding = resource('RoleBinding', 'wiki-deployer', 'wiki', roleRef={'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': 'wiki-deployer'}, subjects=[{'kind': 'ServiceAccount', 'name': 'wiki-deployer', 'namespace': agent_namespace}])
    role['apiVersion'] = binding['apiVersion'] = 'rbac.authorization.k8s.io/v1'
    return [namespace, account, role, binding]


def bootstrap(kube, skip_legacy_git=False):
    infrastructure = prerequisites(kube)
    targets = [
        ('persistentvolumeclaim', 'wiki-runtime-data', 'wiki'),
        ('secret', 'wiki-runtime-bootstrap', 'wiki'),
        ('secret', 'wiki-runtime-git', 'wiki'),
    ]
    existing = [kube.get(*target) for target in targets]
    pvc = resource('PersistentVolumeClaim', 'wiki-runtime-data', 'wiki', spec={'accessModes': ['ReadWriteOnce'], 'storageClassName': 'local-path', 'resources': {'requests': {'storage': '5Gi'}}})
    pvc['metadata']['annotations'] = {'helm.sh/resource-policy': 'keep'}
    if existing[0]:
        spec = existing[0].get('spec', {})
        if spec.get('storageClassName') != 'local-path' or spec.get('accessModes') != ['ReadWriteOnce']:
            raise BootstrapError('Existing wiki-runtime-data PVC has unexpected storage configuration')
    if existing[1]:
        if len(decoded(required_data(existing[1], 'token'))) < 32:
            raise BootstrapError('Existing bootstrap Secret token is unexpectedly short; not overwriting it')
    if existing[2]:
        for key in ('id_ed25519', 'known_hosts'):
            required_data(existing[2], key)
    bootstrap_secret = resource('Secret', 'wiki-runtime-bootstrap', 'wiki', type='Opaque', data={'token': encoded(secrets.token_urlsafe(48))}) if not existing[1] else None
    git_secret = None
    if not existing[2] and not skip_legacy_git:
        key = required_data(kube.get('secret', 'wiki-editor-git', 'wiki'), 'id_ed25519')
        decoded(key)
        hosts = required_data(kube.get('configmap', 'wiki-editor-hosts', 'wiki'), 'known_hosts')
        git_secret = resource('Secret', 'wiki-runtime-git', 'wiki', type='Opaque', data={'id_ed25519': key, 'known_hosts': encoded(hosts)})
    results = []
    for item in infrastructure:
        metadata = item['metadata']
        namespace = metadata.get('namespace', 'wiki')
        old = kube.get(item['kind'].lower(), metadata['name'], namespace)
        if not old:
            kube.create(item)
            results.append(metadata.get('namespace', 'cluster') + '/' + metadata['name'] + ': created')
    for target, old, item in zip(targets, existing, [pvc, bootstrap_secret, git_secret]):
        if not old and item is not None:
            kube.create(item)
        results.append(f'{target[2]}/{target[1]}: ' + ('preserved' if old else 'created' if item is not None else 'skipped'))
    return results


def main():
    parser = argparse.ArgumentParser(description='Create isolated wiki runtime storage and Secret prerequisites without changing routes or deployments')
    parser.add_argument('--kubectl', default='k3s kubectl', help='Executable and arguments, for example kubectl --kubeconfig /path/config')
    parser.add_argument('--skip-legacy-git', action='store_true')
    args = parser.parse_args()
    try:
        command = shlex.split(args.kubectl)
        if not command:
            raise BootstrapError('kubectl command must not be empty')
        for line in bootstrap(Kubernetes(command), args.skip_legacy_git):
            print(line)
    except (BootstrapError, OSError, json.JSONDecodeError):
        parser.exit(1, 'Wiki runtime bootstrap failed; no secret values were printed. Check required source resources and existing target configuration.\n')


if __name__ == '__main__':
    main()
