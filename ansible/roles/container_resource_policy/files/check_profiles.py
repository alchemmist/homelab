import argparse
import copy
import json
import os
import subprocess
import sys

from reconcile_pods import Client, load_profiles, matching_profile, owner, positive, quantity


RESOURCE_NAMES = ('cpu', 'memory', 'ephemeral-storage')


def check(namespace, kubectl, kubeconfig, profile, owner_name):
    command = [kubectl, '--kubeconfig', kubeconfig, '--request-timeout=30s']
    selector = {'resource-policy.socrat.io/probe': 'preserved'}
    selector.update({key: 'previous' for key in profile.get('nodeSelector', {})})
    containers = []
    for name in profile['containers']:
        containers.append({
            'name': name,
            'image': 'registry.k8s.io/pause:3.10',
            'resources': {
                'requests': {'cpu': '1m', 'memory': '1Mi', 'ephemeral-storage': '1Mi'},
                'limits': {'cpu': '8', 'memory': '8Gi', 'ephemeral-storage': '8Gi', 'nvidia.com/gpu': '1'},
            },
        })
    containers.append({'name': 'unprofiled', 'image': 'registry.k8s.io/pause:3.10'})
    for container_type in ('containers', 'initContainers'):
        pod = {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {
                'name': 'resource-profile-check-' + container_type.lower(),
                'namespace': namespace,
                'ownerReferences': [{
                    'apiVersion': 'apps/v1',
                    'kind': profile['ownerKind'],
                    'name': owner_name,
                    'uid': '00000000-0000-0000-0000-000000000001',
                    'controller': True,
                }],
            },
            'spec': {'restartPolicy': 'Never', 'nodeSelector': selector, 'containers': copy.deepcopy(containers)},
        }
        if container_type == 'initContainers':
            del pod['spec']['nodeSelector']
            pod['spec']['containers'] = [{'name': 'main-unprofiled', 'image': 'registry.k8s.io/pause:3.10'}]
            pod['spec']['initContainers'] = copy.deepcopy(containers)
        result = subprocess.run(
            command + ['create', '--dry-run=server', '-o', 'json', '-f', '-'],
            input=json.dumps(pod), text=True, capture_output=True, check=True, timeout=40,
        )
        returned = json.loads(result.stdout)
        expected_selector = dict(pod['spec'].get('nodeSelector', {}), **profile.get('nodeSelector', {}))
        assert returned['spec'].get('nodeSelector', {}) == expected_selector, returned['spec'].get('nodeSelector')
        for container in returned['spec'][container_type]:
            actual = container['resources']
            if container['name'] not in profile['containers']:
                for mode, keys in (('requests', RESOURCE_NAMES), ('limits', ('memory', 'ephemeral-storage'))):
                    assert all(positive(actual.get(mode, {}).get(key)) for key in keys), actual
                assert 'cpu' not in actual.get('limits', {}), actual
                continue
            expected = profile['containers'][container['name']]
            for mode in ('requests', 'limits'):
                for key, value in expected[mode].items():
                    assert quantity(actual[mode][key]) == quantity(value), (container['name'], mode, key, actual, expected)
            if expected.get('removeCpuLimit'):
                assert 'cpu' not in actual.get('limits', {}), actual
            assert actual['limits']['nvidia.com/gpu'] == '1', actual
        print(container_type + ': authoritative profiles and unprofiled fallback passed')
    print('No workload pods created.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kubectl', default='kubectl')
    parser.add_argument('--kubeconfig', default='/etc/rancher/k3s/k3s.yaml')
    parser.add_argument('--profiles', required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    os.environ.setdefault('K3S_CONFIG_FILE', '/dev/null')
    profiles = load_profiles(args.profiles)
    pods = Client(args.kubectl, args.kubeconfig).pods()
    examples = {}
    for pod in pods:
        profile = matching_profile(pod, profiles)
        if profile is not None:
            examples[id(profile)] = owner(pod)['name']
    for profile in profiles:
        if id(profile) not in examples:
            raise ValueError('Profile has no live owner for dry-run verification: ' + str(profile))
    print('Profile schema and live owner matching passed: ' + str(len(profiles)))
    if not args.validate_only:
        for profile in profiles:
            check(profile['namespace'], args.kubectl, args.kubeconfig, profile, examples[id(profile)])


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr or error.stdout or str(error), file=sys.stderr, flush=True)
        sys.exit(1)
    except (ValueError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr, flush=True)
        sys.exit(1)
