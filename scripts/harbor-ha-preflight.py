#!/usr/bin/env python3
"""Read-only, conservative staging-capacity gate; never authorizes production cutover."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024**2
GIB = 1024**3
PROBE = """import json,os
m=dict(line.split(':',1) for line in open('/proc/meminfo'))
p='/var/lib/rancher/k3s/storage'
d=os.statvfs(p)
print(json.dumps({'availableMemoryBytes':int(m['MemAvailable'].split()[0])*1024,'diskAvailableBytes':d.f_bavail*d.f_frsize,'diskTotalBytes':d.f_blocks*d.f_frsize,'storagePath':p}))
"""

def quantity(value):
    value = str(value)
    for suffix, factor in [('Ki', 1024), ('Mi', MIB), ('Gi', GIB), ('Ti', 1024**4),
                           ('K', 1000), ('M', 1000**2), ('G', 1000**3), ('T', 1000**4), ('m', .001)]:
        if value.endswith(suffix):
            return int(Decimal(value[:-len(suffix)]) * Decimal(str(factor)))
    return int(Decimal(value))


def requested_memory(pod):
    # Intentionally conservative: sum all init containers, including restartable
    # sidecars, instead of underestimating their maximum concurrent startup usage.
    spec = pod['spec']
    total = sum(quantity(c.get('resources', {}).get('requests', {}).get('memory', 0))
                for c in spec.get('containers', []) + spec.get('initContainers', []))
    total += quantity(spec.get('overhead', {}).get('memory', 0))
    return max(total, quantity(spec.get('resources', {}).get('requests', {}).get('memory', 0)))


def ssh(policy, node, command):
    return subprocess.check_output(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                                    *policy['nodes'][node]['ssh'], command], text=True, timeout=90)


def collect(policy):
    import shlex
    hosts = {node: json.loads(ssh(policy, node, 'python3 -c ' + shlex.quote(PROBE)))
             for node in policy['nodes']}
    kube = 'env K3S_CONFIG_FILE=/dev/null kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml '
    nodes = json.loads(ssh(policy, 'socrat-0', kube + 'get nodes -o json'))
    # Retrieve pod specs remotely, but only emit per-node aggregate reservations.
    pods = json.loads(ssh(policy, 'socrat-0', kube + 'get pods -A -o json'))
    for node in nodes['items']:
        name = node['metadata']['name']
        if name not in hosts:
            continue
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        hosts[name].update({
            'ready': conditions.get('Ready') == 'True',
            'pressures': [c for c in ['MemoryPressure', 'DiskPressure', 'PIDPressure']
                          if conditions.get(c) != 'False'],
            'unschedulable': node['spec'].get('unschedulable', False),
            'taints': node['spec'].get('taints', []),
            'allocatableMemoryBytes': quantity(node['status']['allocatable']['memory']),
            'requestedMemoryBytes': sum(requested_memory(p) for p in pods['items']
                if p['spec'].get('nodeName') == name and p.get('status', {}).get('phase')
                not in ['Succeeded', 'Failed'])})
    return {'schemaVersion': 1, 'collectedAt': datetime.now(timezone.utc).isoformat(),
            'nodes': hosts}


def check(policy, observation, otel, now=None):
    now = now or datetime.now(timezone.utc)
    age = (now - datetime.fromisoformat(observation['collectedAt'])).total_seconds()
    if age < 0 or age > policy['maximumObservationAgeSeconds']:
        raise ValueError('Observation is stale or future-dated')
    results = {}
    for name, plan in policy['nodes'].items():
        node = observation['nodes'][name]
        future = max(policy['reservedExternalMemoryMiB'][name] * MIB,
                     sum(otel.get('nodes', {}).get(name, {}).get('components', {}).values()))
        additions = sum(plan['componentsMiB'].values()) * MIB
        reserve = policy['hostReserveMiB'] * MIB
        required = additions + future + reserve
        reasons = []
        if not node['ready'] or node['unschedulable'] or node['pressures']:
            reasons.append('node-unhealthy-or-unschedulable')
        if any(t['effect'] in ['NoSchedule', 'NoExecute'] for t in node['taints']):
            reasons.append('untolerated-taint')
        if node['availableMemoryBytes'] < required:
            reasons.append('physical-memory')
        if node['allocatableMemoryBytes'] - node['requestedMemoryBytes'] < additions + future:
            reasons.append('scheduler-memory')
        free_after = node['diskAvailableBytes'] - plan['additionalDiskGiB'] * GIB
        disk_reserve = max(plan['minimumFreeDiskGiB'] * GIB,
                           node['diskTotalBytes'] * policy['minimumFreeDiskFraction'])
        if free_after < disk_reserve:
            reasons.append('disk-reserve')
        results[name] = {'passed': not reasons, 'blockers': reasons,
            'harborAdditionalMiB': additions // MIB, 'otelReservedMiB': future // MIB,
            'requiredAvailableMiB': required // MIB,
            'observedAvailableMiB': node['availableMemoryBytes'] // MIB,
            'schedulerFreeMiB': (node['allocatableMemoryBytes'] - node['requestedMemoryBytes']) // MIB,
            'diskFreeAfterStagingGiB': round(free_after / GIB, 1)}
    return {'passed': all(n['passed'] for n in results.values()), 'nodes': results,
            'cutoverAuthorized': False,
            'scope': 'Conservative staging gate only; no N-1, IOPS, latency, CPU, or restore certification'}


def save_exclusive(path, obj):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(obj, f, indent=2)
        f.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['collect', 'check'])
    parser.add_argument('--policy', type=Path, default=ROOT / 'deploy/harbor/ha-policy.json')
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    if args.action == 'collect':
        result = collect(policy)
    else:
        if args.inventory is None:
            parser.error('--inventory is required for check')
        result = check(policy, json.loads(args.inventory.read_text()),
                       json.loads((ROOT / policy['otelPolicy']).read_text())
                       if (ROOT / policy['otelPolicy']).exists() else {'nodes': {}})
    save_exclusive(args.output, result)
    if args.action == 'check':
        print(json.dumps(result, indent=2))
        return 0 if result['passed'] else 1
    print('Read-only capacity inventory saved; no credentials or application logs collected.')
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        print('Preflight failed: ' + str(exc), file=sys.stderr)
        sys.exit(2)
