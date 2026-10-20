import argparse
import json
import os
import re
import subprocess
import sys
import time
from decimal import Decimal, InvalidOperation


RESOURCE_NAMES = ('cpu', 'memory', 'ephemeral-storage')
LIMIT_RESOURCE_NAMES = ('memory', 'ephemeral-storage')
SUPPORTED_OWNERS = {'ReplicaSet', 'DaemonSet', 'StatefulSet'}
QUANTITY = re.compile(r'^([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))([eE][+-]?[0-9]+|[numkKMGTP E]i?)?$'.replace(' ', ''))


def quantity(value):
    match = QUANTITY.fullmatch(str(value)) if value is not None else None
    if not match:
        raise ValueError('Invalid resource quantity: ' + str(value))
    number = Decimal(match.group(1))
    suffix = match.group(2) or ''
    if suffix.startswith(('e', 'E')) and len(suffix) > 1 and suffix[1] in '+-0123456789':
        return number * Decimal(10) ** int(suffix[1:])
    if suffix.endswith('i'):
        return number * Decimal(1024) ** ('KMGTPE'.index(suffix[0]) + 1)
    powers = {'': 0, 'n': -9, 'u': -6, 'm': -3, 'k': 3, 'K': 3, 'M': 6, 'G': 9, 'T': 12, 'P': 15, 'E': 18}
    if suffix not in powers:
        raise ValueError('Invalid resource suffix: ' + suffix)
    return number * Decimal(10) ** powers[suffix]


def positive(value):
    try:
        return quantity(value) > 0
    except (ValueError, InvalidOperation):
        return False


def load_profiles(path):
    with open(path) as source:
        profiles = json.load(source)
    if not isinstance(profiles, list):
        raise ValueError('Profiles must be a JSON list')
    for profile in profiles:
        if not all(isinstance(profile.get(key), str) and profile[key] for key in ('namespace', 'ownerKind', 'ownerPattern')):
            raise ValueError('Profile requires namespace, ownerKind, and ownerPattern')
        pattern = profile['ownerPattern']
        if not pattern.startswith('^') or not pattern.endswith('$'):
            raise ValueError('Profile ownerPattern must be anchored with ^ and $')
        re.compile(pattern)
        if not isinstance(profile.get('containers'), dict) or not profile['containers']:
            raise ValueError('Profile requires a nonempty containers map')
        for resources in profile['containers'].values():
            if not isinstance(resources.get('removeCpuLimit', False), bool):
                raise ValueError('removeCpuLimit must be boolean')
            requests, limits = resources.get('requests', {}), resources.get('limits', {})
            if resources.get('removeCpuLimit') and 'cpu' in limits:
                raise ValueError('Cannot remove and set CPU limit together')
            if not resources.get('removeCpuLimit') and 'cpu' not in limits:
                raise ValueError('Profile must set CPU limit or explicitly remove it')
            for resource in RESOURCE_NAMES:
                if not positive(requests.get(resource)):
                    raise ValueError('Profile must specify positive requests/' + resource)
            for resource in LIMIT_RESOURCE_NAMES:
                if not positive(limits.get(resource)):
                    raise ValueError('Profile must specify positive limits/' + resource)
            for resource, limit in limits.items():
                if resource not in RESOURCE_NAMES or not positive(limit):
                    raise ValueError('Invalid profile limit: ' + resource)
                if quantity(requests[resource]) > quantity(limit):
                    raise ValueError('Profile request exceeds limit: ' + resource)
    return profiles


def matching_profile(pod, profiles):
    reference = owner(pod)
    matches = [profile for profile in profiles if reference and profile['namespace'] == pod['metadata']['namespace'] and profile['ownerKind'] == reference['kind'] and re.fullmatch(profile['ownerPattern'], reference.get('name', ''))]
    if len(matches) > 1:
        raise RuntimeError('Ambiguous resource profiles for ' + label(pod))
    return matches[0] if matches else None


def profile_mismatches(pod, profile):
    if profile is None:
        return []
    mismatches = []
    present = set()
    for kind in ('containers', 'initContainers'):
        for container in pod.get('spec', {}).get(kind, []):
            name = container['name']
            present.add(name)
            if name not in profile['containers']:
                mismatches.append(kind + '/' + name + '/missing-profile')
                continue
            expected = profile['containers'][name]
            for mode in ('requests', 'limits'):
                for resource, desired in expected[mode].items():
                    actual = container.get('resources', {}).get(mode, {}).get(resource)
                    if not positive(actual) or quantity(actual) != quantity(desired):
                        mismatches.append(kind + '/' + name + '/' + mode + '/' + resource)
            if expected.get('removeCpuLimit') and 'cpu' in container.get('resources', {}).get('limits', {}):
                mismatches.append(kind + '/' + name + '/limits/cpu-present')
    for name in profile['containers'].keys() - present:
        mismatches.append(name + '/missing-container')
    return mismatches


def needs_reconcile(pod, profiles=()):
    return bool(deficits(pod) or profile_mismatches(pod, matching_profile(pod, profiles)))


def deficits(pod):
    missing = []
    for kind in ('containers', 'initContainers'):
        for container in pod.get('spec', {}).get(kind, []):
            resources = container.get('resources', {})
            for mode, required in (('requests', RESOURCE_NAMES), ('limits', LIMIT_RESOURCE_NAMES)):
                for resource in required:
                    if not positive(resources.get(mode, {}).get(resource)):
                        missing.append(kind + '/' + container['name'] + '/' + mode + '/' + resource)
    return missing


def active(pod):
    return pod.get('status', {}).get('phase') not in ('Succeeded', 'Failed')


def owner(pod):
    return next((item for item in pod['metadata'].get('ownerReferences', []) if item.get('controller')), None)


def supported(pod):
    reference = owner(pod)
    return bool(reference and reference['kind'] in SUPPORTED_OWNERS and not pod['metadata'].get('annotations', {}).get('kubernetes.io/config.mirror'))


def ready(pod):
    return active(pod) and not pod['metadata'].get('deletionTimestamp') and any(item.get('type') == 'Ready' and item.get('status') == 'True' for item in pod.get('status', {}).get('conditions', []))


def same_workload(original, candidate):
    original_owner, candidate_owner = owner(original), owner(candidate)
    if not original_owner or not candidate_owner:
        return False
    if original['metadata']['namespace'] != candidate['metadata']['namespace'] or original_owner['uid'] != candidate_owner['uid']:
        return False
    if original_owner['kind'] == 'DaemonSet':
        return original.get('spec', {}).get('nodeName') == candidate.get('spec', {}).get('nodeName')
    if original_owner['kind'] == 'StatefulSet':
        return original['metadata']['name'] == candidate['metadata']['name']
    return True


def eviction_payload(pod):
    metadata = pod['metadata']
    return {'apiVersion': 'policy/v1', 'kind': 'Eviction', 'metadata': {'namespace': metadata['namespace'], 'name': metadata['name']}, 'deleteOptions': {'preconditions': {'uid': metadata['uid']}}}


class Client:
    def __init__(self, kubectl, kubeconfig):
        self.command = [kubectl, '--kubeconfig', kubeconfig, '--request-timeout=30s']

    def pods(self):
        result = subprocess.run(self.command + ['get', 'pods', '--all-namespaces', '-o', 'json'], capture_output=True, text=True, check=True, timeout=40)
        return json.loads(result.stdout)['items']

    def evict(self, pod):
        metadata = pod['metadata']
        endpoint = '/api/v1/namespaces/' + metadata['namespace'] + '/pods/' + metadata['name'] + '/eviction'
        return subprocess.run(self.command + ['create', '--raw', endpoint, '-f', '-'], input=json.dumps(eviction_payload(pod)), capture_output=True, text=True, timeout=40)


def label(pod):
    return pod['metadata']['namespace'] + '/' + pod['metadata']['name']


def excluded(pod, nodes):
    spec = pod.get('spec', {})
    return spec.get('nodeName') in nodes or spec.get('nodeSelector', {}).get('kubernetes.io/hostname') in nodes


def audit(pods, excluded_nodes=(), profiles=()):
    active_pods = [pod for pod in pods if active(pod)]
    coverage = [(pod, matching_profile(pod, profiles)) for pod in active_pods]
    deficient = [pod for pod in active_pods if needs_reconcile(pod, profiles)]
    if profiles:
        for pod, profile in coverage:
            if profile is None:
                print(json.dumps({'pod': label(pod), 'profile': 'unmatched', 'owner': owner(pod)}), flush=True)
    for pod in deficient:
        print(json.dumps({'pod': label(pod), 'uid': pod['metadata']['uid'], 'owner': owner(pod), 'supported': supported(pod), 'excluded': excluded(pod, excluded_nodes), 'node': pod.get('spec', {}).get('nodeName'), 'missing_resources': deficits(pod), 'profile_mismatches': profile_mismatches(pod, matching_profile(pod, profiles))}), flush=True)
    actionable = [pod for pod in deficient if not excluded(pod, excluded_nodes)]
    summary = {'active': sum(active(pod) for pod in pods), 'deficient': len(deficient), 'actionable_deficient': len(actionable), 'excluded_deficient': len(deficient) - len(actionable), 'excluded_nodes': sorted(excluded_nodes), 'unsupported': sum(not supported(pod) for pod in actionable), 'profiled_active': sum(profile is not None for _, profile in coverage), 'unprofiled_active': sum(profile is None for _, profile in coverage)}
    print(json.dumps({'summary': summary}), flush=True)
    return actionable


def reconcile_one(client, original, timeout, interval, profiles=()):
    deadline = time.monotonic() + timeout
    before = client.pods()
    current = next((pod for pod in before if pod['metadata']['uid'] == original['metadata']['uid']), None)
    if current is None or not active(current) or not needs_reconcile(current, profiles):
        print('Already replaced or compliant: ' + label(original), flush=True)
        return
    previous_uids = {pod['metadata']['uid'] for pod in before if same_workload(original, pod)}
    print('Evicting: ' + label(original), flush=True)
    while time.monotonic() < deadline:
        result = client.evict(original)
        if result.returncode == 0:
            break
        error = result.stderr + result.stdout
        if 'TooManyRequests' not in error and '429' not in error and 'disruption budget' not in error.lower():
            raise RuntimeError('Eviction failed for ' + label(original) + ': ' + error.strip())
        print('Waiting for disruption budget: ' + label(original), flush=True)
        time.sleep(interval)
    else:
        raise TimeoutError('Disruption budget timeout: ' + label(original))
    while time.monotonic() < deadline:
        pods = client.pods()
        old_present = any(pod['metadata']['uid'] == original['metadata']['uid'] for pod in pods)
        replacements = [pod for pod in pods if same_workload(original, pod) and pod['metadata']['uid'] not in previous_uids]
        valid = [pod for pod in replacements if ready(pod) and not needs_reconcile(pod, profiles)]
        if not old_present and valid:
            print('Ready with desired resources: ' + label(valid[0]), flush=True)
            return
        time.sleep(interval)
    raise TimeoutError('Replacement did not become Ready with desired resources: ' + label(original))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--profiles')
    parser.add_argument('--exclude-node', action='append', default=[])
    parser.add_argument('--kubectl', default='kubectl')
    parser.add_argument('--kubeconfig', default='/etc/rancher/k3s/k3s.yaml')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--poll-interval', type=float, default=5)
    args = parser.parse_args()
    if args.timeout <= 0 or args.poll_interval <= 0:
        parser.error('Timeout and poll interval must be positive')
    os.environ.setdefault('K3S_CONFIG_FILE', '/dev/null')
    profiles = load_profiles(args.profiles) if args.profiles else []
    client = Client(args.kubectl, args.kubeconfig)
    deficient = audit(client.pods(), set(args.exclude_node), profiles)
    if not args.apply:
        return
    unsupported = [label(pod) for pod in deficient if not supported(pod)]
    if unsupported:
        raise RuntimeError('Active deficient pods require manual owner handling before rollout: ' + ', '.join(unsupported))
    for pod in deficient:
        reconcile_one(client, pod, args.timeout, args.poll_interval, profiles)
    remaining = audit(client.pods(), set(args.exclude_node), profiles)
    if remaining:
        raise RuntimeError('Some active pods still lack required resources or differ from their profile')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, TimeoutError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr, flush=True)
        sys.exit(1)
