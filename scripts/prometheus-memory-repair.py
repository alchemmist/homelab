#!/usr/bin/env python3
"""Reconcile ONLY Prometheus RAM admission scalars and resize its existing Pod.

No restarts, eviction, StatefulSet edits, metrics retention or storage mutation.
Run on socrat-0 with existing kubectl access. Private receipts prevent replay.
"""
import argparse
import copy
import json
import importlib.util
import os
from pathlib import Path
import re
import subprocess

NS = 'cattle-monitoring-system'
NAME = 'prometheus-kube-prometheus-stack-prometheus-0'
STS = 'prometheus-kube-prometheus-stack-prometheus'
POLICY = 'socrat-container-resource-defaults'
PATTERN = '^prometheus\\-kube\\-prometheus\\-stack\\-prometheus$'
RECEIPT = Path.home() / '.cache/homelab-recovery/20261114-prometheus-memory'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def expression_change(expr):
    needle = '"ownerPattern": dyn(' + json.dumps(PATTERN) + ')'
    require(expr.count(needle) == 1, 'Prometheus profile not unique')
    start = expr.index(needle)
    next_profile = expr.find('"ownerPattern"', start + len(needle))
    end_profile = next_profile if next_profile >= 0 else len(expr)
    begin = expr.find('"prometheus": {', start, end_profile)
    require(begin >= 0, 'Prometheus container profile missing')
    # CEL wraps values in dyn(...), but braces and JSON strings are balanced.
    # Do not depend on the indentation used by a previous Ansible renderer.
    depth, quoted, escaped, end = 0, False, False, None
    for index in range(expr.index('{', begin), end_profile):
        char = expr[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    require(end is not None, 'Unbalanced container profile')
    block = expr[begin:end]
    require(block.count('"memory"') == 2, 'Unexpected RAM fields')
    for group, old, new in [('requests', '2048Mi', '3072Mi'), ('limits', '3072Mi', '8192Mi')]:
        pattern = r'("' + group + r'": dyn\(\{[^}]*"memory": ")([^\"]+)(")'
        match = re.search(pattern, block)
        require(match is not None and match.group(2) == old, 'Unexpected current ' + group + ' RAM')
        block = block[:match.start(2)] + new + block[match.end(2):]
    return expr[:begin] + block + expr[end:]


def policy_patch(policy):
    variables = policy['spec']['variables']
    indexes = [i for i, v in enumerate(variables) if v['name'] == 'profiles']
    require(len(indexes) == 1, 'Profiles variable not unique')
    index = indexes[0]
    old = variables[index]['expression']
    new = expression_change(old)
    path = f'/spec/variables/{index}/expression'
    return [{'op': 'test', 'path': '/metadata/uid', 'value': policy['metadata']['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': policy['metadata']['resourceVersion']},
            {'op': 'test', 'path': path, 'value': old},
            {'op': 'replace', 'path': path, 'value': new}]


def resize_patch(pod):
    require(pod['metadata']['name'] == NAME and pod['metadata']['namespace'] == NS, 'Wrong Pod')
    require(pod['spec']['nodeName'] == 'socrat-0', 'Wrong node')
    require(any(o.get('controller') and o['kind'] == 'StatefulSet' and o['name'] == STS
                for o in pod['metadata']['ownerReferences']), 'Wrong controller')
    containers = pod['spec']['containers']
    indexes = [i for i, c in enumerate(containers) if c['name'] == 'prometheus']
    require(len(indexes) == 1, 'Prometheus container not unique')
    i = indexes[0]
    c = containers[i]
    require(c['resources']['requests']['memory'] in ('2Gi', '2048Mi') and
            c['resources']['limits']['memory'] in ('3Gi', '3072Mi'), 'Unexpected current Pod RAM')
    require(not any(p['resourceName'] == 'memory' and p['restartPolicy'] != 'NotRequired'
                    for p in c.get('resizePolicy', [])), 'Memory resize would restart container')
    root = f'/spec/containers/{i}/resources'
    return [{'op': 'test', 'path': '/metadata/uid', 'value': pod['metadata']['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': pod['metadata']['resourceVersion']},
            {'op': 'test', 'path': root, 'value': c['resources']},
            {'op': 'replace', 'path': root + '/requests/memory', 'value': '3Gi'},
            {'op': 'replace', 'path': root + '/limits/memory', 'value': '8Gi'}]


def kubectl(args, data=None):
    env = dict(os.environ, K3S_CONFIG_FILE='/dev/null')
    p = subprocess.run(['kubectl', '--request-timeout=10s', *args],
                       input=json.dumps(data) if data is not None else None,
                       capture_output=True, text=True, env=env, timeout=20)
    require(p.returncode == 0, 'kubectl failed: ' + p.stderr[:500])
    return json.loads(p.stdout)


def save(name, data):
    fd = os.open(RECEIPT / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(data, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    directory = os.open(RECEIPT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def probe(sts):
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': 'prometheus-memory-admission-probe', 'namespace': NS,
                         'ownerReferences': [{'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
                         'name': STS, 'uid': sts['metadata']['uid'], 'controller': True}]},
            'spec': {'restartPolicy': 'Never', 'containers': [{'name': 'prometheus',
                     'image': sts['spec']['template']['spec']['containers'][0]['image'],
                     'command': ['/bin/true'], 'resources': {'requests': {'memory': '3Gi'},
                                                           'limits': {'memory': '8Gi'}}}]}}


def memory_capacity(node, pods):
    budget_path = Path(__file__).with_name('check-resource-budget.py')
    spec = importlib.util.spec_from_file_location('resource_budget', budget_path)
    budget = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(budget)
    active = [p for p in pods if p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')]
    used = sum(budget.effective_requests(p)['memory'] for p in active)
    alloc = budget.quantity(node['status']['allocatable']['memory'])
    projected = used + budget.quantity('1Gi')
    require(projected <= alloc, 'Insufficient node reservation capacity; no mutation')
    return {'current_requests_bytes': int(used), 'projected_requests_bytes': int(projected),
            'allocatable_bytes': int(alloc), 'projected_remaining_bytes': int(alloc - projected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    require(not RECEIPT.exists(), 'Prior attempt exists; inspect receipt, do not replay')
    policy = kubectl(['get', 'mutatingadmissionpolicy', POLICY, '-o', 'json'])
    pod = kubectl(['-n', NS, 'get', 'pod', NAME, '-o', 'json'])
    sts = kubectl(['-n', NS, 'get', 'statefulset', STS, '-o', 'json'])
    cr = kubectl(['-n', NS, 'get', 'prometheus', 'kube-prometheus-stack-prometheus', '-o', 'json'])
    require(cr['spec']['resources']['requests']['memory'] == '4Gi' and
            cr['spec']['resources']['limits']['memory'] == '8Gi', 'Desired Prometheus CR RAM differs')
    node = kubectl(['get', 'node', 'socrat-0', '-o', 'json'])
    pods = kubectl(['get', 'pods', '-A', '--field-selector=spec.nodeName=socrat-0', '-o', 'json'])['items']
    capacity = memory_capacity(node, pods)
    pp = policy_patch(policy)
    rp = resize_patch(pod)
    statuses = {c['name']: c['containerID'] for c in pod['status']['containerStatuses']}
    require(all(c['ready'] for c in pod['status']['containerStatuses']), 'Existing Pod not ready')
    # Validate both API paths before any mutation. The same-Pod scheduler admits request growth.
    kubectl(['patch', 'mutatingadmissionpolicy', POLICY, '--type=json', '-p', json.dumps(pp),
             '--dry-run=server', '-o', 'json'])
    kubectl(['-n', NS, 'patch', 'pod', NAME, '--subresource=resize', '--type=json',
             '-p', json.dumps(rp), '--dry-run=server', '-o', 'json'])
    result = {'preflight': 'accepted', 'pod_uid': pod['metadata']['uid'],
              'old_limit': '3Gi', 'new_limit': '8Gi', 'request': '3Gi', 'restart': False, 'capacity': capacity}
    if not args.apply:
        print(json.dumps(result))
        return
    RECEIPT.mkdir(parents=True, mode=0o700)
    os.chmod(RECEIPT, 0o700)
    save('before-policy.private.json', policy)
    save('before-pod.private.json', pod)
    save('intent.private.json', {'policy_patch': pp, 'resize_patch': rp})
    updated = kubectl(['patch', 'mutatingadmissionpolicy', POLICY, '--type=json', '-p', json.dumps(pp), '-o', 'json'])
    save('policy-applied.private.json', updated)
    try:
        future = kubectl(['create', '--dry-run=server', '-f', '-', '-o', 'json'], probe(sts))
        future_ram = future['spec']['containers'][0]['resources']
        require(future_ram['requests']['memory'] in ('3Gi', '3072Mi') and
                future_ram['limits']['memory'] in ('8Gi', '8192Mi'), 'Future-Pod admission did not converge')
    except Exception:
        current = kubectl(['get', 'mutatingadmissionpolicy', POLICY, '-o', 'json'])
        reverse = copy.deepcopy(pp)
        reverse[1]['value'] = current['metadata']['resourceVersion']
        reverse[2]['value'], reverse[3]['value'] = pp[3]['value'], pp[2]['value']
        kubectl(['patch', 'mutatingadmissionpolicy', POLICY, '--type=json', '-p', json.dumps(reverse), '-o', 'json'])
        save('admission-rolled-back.json', {'rolled_back': True})
        raise
    save('future-admission.private.json', future)
    # Fresh RV; refuse if Pod or current resources changed after preflight.
    fresh = kubectl(['-n', NS, 'get', 'pod', NAME, '-o', 'json'])
    require(fresh['metadata']['uid'] == pod['metadata']['uid'], 'Pod replaced during preflight')
    rp = resize_patch(fresh)
    resized = kubectl(['-n', NS, 'patch', 'pod', NAME, '--subresource=resize', '--type=json',
                       '-p', json.dumps(rp), '-o', 'json'])
    require(resized['metadata']['uid'] == pod['metadata']['uid'], 'Pod UID changed')
    require({c['name']: c['containerID'] for c in resized['status']['containerStatuses']} == statuses,
            'Container identity changed; inspect immediately')
    save('resize-accepted.private.json', resized)
    print(json.dumps({**result, 'applied': True, 'future_admission': '3Gi/8Gi',
                      'receipt': str(RECEIPT), 'runtime_acceptance': 'pending cgroup and telemetry verification'}))


if __name__ == '__main__':
    main()
