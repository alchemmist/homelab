import argparse
import copy
from decimal import Decimal
import json
import re
import sys


RESOURCES = ('cpu', 'memory', 'ephemeral-storage')
QUANTITY = re.compile(r'^([+-]?(?:\d+(?:\.\d*)?|\.\d+))([eE][+-]?\d+|[numkKMGTPE]|[KMGTPE]i)?$')


def quantity(value):
    match = QUANTITY.fullmatch(str(value))
    if not match:
        raise ValueError('Invalid resource quantity: ' + str(value))
    number = Decimal(match[1])
    suffix = match[2] or ''
    if suffix.startswith(('e', 'E')) and len(suffix) > 1 and not suffix.endswith('i'):
        result = number * Decimal(10) ** int(suffix[1:])
    elif suffix.endswith('i'):
        result = number * Decimal(1024) ** ('KMGTPE'.index(suffix[0]) + 1)
    else:
        result = number * Decimal(10) ** {'': 0, 'n': -9, 'u': -6, 'm': -3, 'k': 3, 'K': 3, 'M': 6, 'G': 9, 'T': 12, 'P': 15, 'E': 18}[suffix]
    if result < 0:
        raise ValueError('Negative resource quantity: ' + str(value))
    return result


def vector(values=None):
    return {name: quantity((values or {}).get(name, 0)) for name in RESOURCES}


def add(left, right):
    return {name: left[name] + right[name] for name in RESOURCES}


def maximum(left, right):
    return {name: max(left[name], right[name]) for name in RESOURCES}


def effective_requests(pod):
    spec = pod.get('spec', {})
    total, sidecars, init_peak = vector(), vector(), vector()
    for container in spec.get('containers', []):
        total = add(total, vector(container.get('resources', {}).get('requests')))
    for container in spec.get('initContainers', []):
        requested = vector(container.get('resources', {}).get('requests'))
        if container.get('restartPolicy') == 'Always':
            sidecars = add(sidecars, requested)
            init_peak = maximum(init_peak, sidecars)
        else:
            init_peak = maximum(init_peak, add(sidecars, requested))
    total = maximum(add(total, sidecars), init_peak)
    for name, value in spec.get('resources', {}).get('requests', {}).items():
        if name in RESOURCES:
            total[name] = quantity(value)
    return add(total, vector(spec.get('overhead')))


def proposed_pod(pod, profiles):
    label = pod['metadata'].get('namespace', 'default') + '/' + pod['metadata']['name']
    owner = next((value for value in pod['metadata'].get('ownerReferences', []) if value.get('controller')), {})
    matches = [profile for profile in profiles if profile['namespace'] == pod['metadata'].get('namespace', 'default') and profile['ownerKind'] == owner.get('kind') and re.fullmatch(profile['ownerPattern'], owner.get('name', ''))]
    if len(matches) != 1:
        raise ValueError(label + ': ' + ('ambiguous profiles' if matches else 'unmatched profile'))
    expected = matches[0]['containers']
    result = copy.deepcopy(pod)
    present = set()
    for field in ('containers', 'initContainers'):
        for container in result.get('spec', {}).get(field, []):
            name = container['name']
            present.add(name)
            if name not in expected:
                raise ValueError(label + '/' + name + ': unmatched container')
            resources = container.setdefault('resources', {})
            for mode in ('requests', 'limits'):
                resources.setdefault(mode, {}).update(expected[name].get(mode, {}))
            if expected[name].get('removeCpuLimit'):
                resources['limits'].pop('cpu', None)
    if set(expected) - present:
        raise ValueError(label + ': profile contains absent containers ' + ', '.join(sorted(set(expected) - present)))
    return result


def items(value):
    return value['items'] if isinstance(value, dict) else value


def validate_profiles(profiles):
    if not isinstance(profiles, list):
        raise ValueError('Profiles must be a JSON list')
    for profile in profiles:
        for name in ('namespace', 'ownerKind', 'ownerPattern'):
            if not isinstance(profile.get(name), str) or not profile[name]:
                raise ValueError('Profile requires ' + name)
        re.compile(profile['ownerPattern'])
        if not isinstance(profile.get('containers'), dict) or not profile['containers']:
            raise ValueError('Profile requires containers')
        for resources in profile['containers'].values():
            requests = resources.get('requests', {})
            for name in RESOURCES:
                if name not in requests or quantity(requests[name]) <= 0:
                    raise ValueError('Profile requires positive requests/' + name)
            for name, limit in resources.get('limits', {}).items():
                if name in RESOURCES and quantity(limit) < quantity(requests[name]):
                    raise ValueError('Profile limit below request: ' + name)
            if not isinstance(resources.get('removeCpuLimit', False), bool):
                raise ValueError('removeCpuLimit must be boolean')
            if resources.get('removeCpuLimit') and 'cpu' in resources.get('limits', {}):
                raise ValueError('Profile cannot set and remove CPU limit')


def budget(pods, nodes, profiles):
    validate_profiles(profiles)
    report = {'scope': 'Current placement only; not a scheduler simulation or an N-1, rollout, peak-use or memory-safety guarantee. Requests are not actual usage. Unassigned pods are not charged to any node.', 'nodes': {}, 'unassigned': [], 'errors': []}
    for node in items(nodes):
        report['nodes'][node['metadata']['name']] = {'allocatable': vector(node['status']['allocatable']), 'current_requests': vector(), 'proposed_requests': vector(), 'pods': 0}
    for pod in items(pods):
        if pod.get('status', {}).get('phase') in ('Succeeded', 'Failed'):
            continue
        label = pod['metadata'].get('namespace', 'default') + '/' + pod['metadata']['name']
        try:
            proposed = proposed_pod(pod, profiles)
        except ValueError as error:
            report['errors'].append(str(error))
            proposed = pod
        current, future = effective_requests(pod), effective_requests(proposed)
        node_name = pod.get('spec', {}).get('nodeName')
        if not node_name:
            report['unassigned'].append({'pod': label, 'current_requests': current, 'proposed_requests': future})
            continue
        if node_name not in report['nodes']:
            report['errors'].append(label + ': unknown node ' + node_name)
            continue
        entry = report['nodes'][node_name]
        entry['pods'] += 1
        entry['current_requests'] = add(entry['current_requests'], current)
        entry['proposed_requests'] = add(entry['proposed_requests'], future)
    for name, node in report['nodes'].items():
        for mode in ('current', 'proposed'):
            node[mode + '_remaining'] = {resource: node['allocatable'][resource] - node[mode + '_requests'][resource] for resource in RESOURCES}
        for resource, remaining in node['proposed_remaining'].items():
            if remaining < 0:
                report['errors'].append(name + ': proposed requests exceed allocatable ' + resource)
    report['ok'] = not report['errors']
    report['units'] = {'cpu': 'cores', 'memory': 'bytes', 'ephemeral-storage': 'bytes'}
    return report


def main():
    parser = argparse.ArgumentParser(description='Read-only current-placement request budget comparison')
    for name in ('pods', 'nodes', 'profiles'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        values = []
        for path in (args.pods, args.nodes, args.profiles):
            with open(path) as source:
                values.append(json.load(source))
        report = budget(*values)
        print(json.dumps(report, indent=2, default=lambda value: str(value) if isinstance(value, Decimal) else value))
        return 0 if report['ok'] else 1
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
