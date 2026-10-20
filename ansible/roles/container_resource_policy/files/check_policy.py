import argparse
import json
import os
import subprocess
import sys


RESOURCE_NAMES = ('cpu', 'memory', 'ephemeral-storage')


def check(namespace, kubectl, kubeconfig):
    command = [kubectl, '--kubeconfig', kubeconfig, '--request-timeout=30s']
    cases = [
        ('empty', {}),
        ('memory-only', {'limits': {'memory': '256Mi'}}),
        ('high-request', {'requests': {'cpu': '4', 'memory': '2Gi', 'ephemeral-storage': '8Gi'}}),
        ('small-limit', {'limits': {'cpu': '5m', 'memory': '16Mi', 'ephemeral-storage': '8Mi'}}),
        ('gpu', {'limits': {'nvidia.com/gpu': '1'}}),
        ('zero-limits', {'limits': dict.fromkeys(RESOURCE_NAMES, '0')}),
        ('explicit', {
            'requests': {'cpu': '250m', 'memory': '512Mi', 'ephemeral-storage': '100Mi'},
            'limits': {'cpu': '6', 'memory': '2Gi', 'ephemeral-storage': '10Gi'},
        }),
    ]
    for case, resources in cases:
        pod = {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {'name': 'resource-policy-check-' + case, 'namespace': namespace},
            'spec': {
                'restartPolicy': 'Never',
                'containers': [{'name': 'main', 'image': 'registry.k8s.io/pause:3.10', 'resources': resources}],
                'initContainers': [{'name': 'init', 'image': 'registry.k8s.io/pause:3.10', 'resources': resources}],
            },
        }
        result = subprocess.run(
            command + ['create', '--dry-run=server', '-o', 'json', '-f', '-'],
            input=json.dumps(pod), text=True, capture_output=True, check=True, timeout=40,
        )
        returned = json.loads(result.stdout)
        for container_type in ('containers', 'initContainers'):
            actual = returned['spec'][container_type][0]['resources']
            for mode, keys in (('requests', RESOURCE_NAMES), ('limits', ('memory', 'ephemeral-storage'))):
                if not all(key in actual.get(mode, {}) for key in keys):
                    raise AssertionError((case, container_type, actual))
            if any(actual['limits'][key] == '0' for key in ('memory', 'ephemeral-storage')):
                raise AssertionError((case, container_type, actual))
            if case == 'zero-limits' and 'cpu' in actual['limits']:
                raise AssertionError(('Zero CPU limit must be removed', case, container_type, actual))
            if case == 'gpu' and actual['limits'].get('nvidia.com/gpu') != '1':
                raise AssertionError((case, container_type, actual))
            if case == 'high-request' and any(actual['limits'].get(key) != resources['requests'][key] for key in ('memory', 'ephemeral-storage')):
                raise AssertionError((case, container_type, actual))
            if 'cpu' not in resources.get('limits', {}) and 'cpu' in actual['limits']:
                raise AssertionError(('Unexpected CPU cap', case, container_type, actual))
            if case == 'small-limit' and actual['requests'] != resources['limits']:
                raise AssertionError((case, container_type, actual))
            if case == 'explicit' and actual != resources:
                raise AssertionError((case, container_type, actual))
        print(case + ': passed')
    print('All 7 server-side dry-run cases passed for regular and init containers; no pods created.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--kubectl', default='kubectl')
    parser.add_argument('--kubeconfig', default='/etc/rancher/k3s/k3s.yaml')
    args = parser.parse_args()
    os.environ.setdefault('K3S_CONFIG_FILE', '/dev/null')
    check(args.namespace, args.kubectl, args.kubeconfig)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr or error.stdout or str(error), file=sys.stderr, flush=True)
        sys.exit(1)
    except (ValueError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr, flush=True)
        sys.exit(1)
