#!/usr/bin/env python3
"""Bounded read-only convergence check; replica0 or old Ready Pods never pass."""
import argparse
import json
import shlex
import subprocess
import time


def converged(deployment, pods, node, replicas=1):
    spec, status = deployment['spec'], deployment.get('status', {})
    if replicas < 1 or spec.get('replicas') != replicas:
        return False
    if status.get('observedGeneration', 0) < deployment['metadata']['generation']:
        return False
    if status.get('updatedReplicas', 0) != replicas or status.get('readyReplicas', 0) != replicas:
        return False
    if len(pods) != replicas:
        return False
    for pod in pods:
        if pod['metadata'].get('deletionTimestamp') or pod['spec'].get('nodeName') != node:
            return False
        states = pod.get('status', {}).get('containerStatuses', [])
        if len(states) != len(pod['spec']['containers']) or not all(c.get('ready') for c in states):
            return False
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--namespace', required=True)
    p.add_argument('--deployment', required=True)
    p.add_argument('--node', required=True)
    p.add_argument('--host', default='socrat-0')
    p.add_argument('--timeout', type=int, default=300)
    args = p.parse_args()
    if args.timeout < 1 or args.timeout > 1800:
        p.error('timeout must be 1..1800 seconds')
    deadline = time.monotonic() + args.timeout

    def get(kind, *extra):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Placement did not converge before deadline')
        command = ['kubectl', '--kubeconfig=/etc/rancher/k3s/k3s.yaml',
                   '--request-timeout=15s', '-n', args.namespace, 'get', kind, *extra, '-o', 'json']
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                                 args.host, shlex.join(command)], capture_output=True, text=True,
                                timeout=min(remaining, 25))
        if result.returncode:
            raise RuntimeError('Read-only Kubernetes inspection failed; inspect transport privately')
        return json.loads(result.stdout)

    while time.monotonic() < deadline:
        d = get('deployment', args.deployment)
        selector = d['spec']['selector']
        if selector.get('matchExpressions'):
            raise ValueError('Complex selector unsupported; refusing partial ownership check')
        labels = ','.join(k+'='+v for k, v in sorted(selector['matchLabels'].items()))
        pods = get('pods', '-l', labels)['items']
        if converged(d, pods, args.node):
            # Validate ownership as well as labels. A manually labelled Pod is not proof.
            sets = get('replicasets', '-l', labels)['items']
            owned = {r['metadata']['uid'] for r in sets
                     if any(o.get('controller') and o['uid'] == d['metadata']['uid']
                            for o in r['metadata'].get('ownerReferences', []))}
            if not all(any(o.get('controller') and o['uid'] in owned
                           for o in pod['metadata'].get('ownerReferences', [])) for pod in pods):
                raise ValueError('Ready Pod not owned by target Deployment')
            print(f'{args.deployment}: one Ready owned Pod on {args.node}; observed desired generation')
            return
        time.sleep(min(2, max(0, deadline-time.monotonic())))
    raise TimeoutError('Placement did not converge before deadline; not accepted')

if __name__ == '__main__':
    main()
