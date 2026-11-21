"""Remove only the two legacy pins; don't replay unrelated live admission drift."""

import argparse
import json
import subprocess

POLICY = 'socrat-container-resource-defaults'
PATTERNS = (r'^local\-path\-provisioner-[a-z0-9]+$', r'^metrics\-server-[a-z0-9]+$')


def patch_for(obj):
    """Execute the patch_for operation."""
    variables = obj['spec']['variables']
    idx, = [i for i, v in enumerate(variables) if v['name'] == 'profiles']
    old = variables[idx]['expression']
    new = old
    for pattern in PATTERNS:
        prefix = '\n'.join(('    "namespace": dyn("kube-system"),', '    "ownerKind": dyn("ReplicaSet"),',
                            f'    "ownerPattern": dyn({json.dumps(pattern)}),', '    "nodeSelector": dyn('))
        pinned = prefix + '{"kubernetes.io/hostname": "socrat-1"})'
        unpinned = prefix + '{})'
        if new.count(prefix) != 1 or new.count(pinned) + new.count(unpinned) != 1:
            raise ValueError(f'Unexpected live admission profile: {pattern}; refusing to patch')
        new = new.replace(pinned, unpinned)
    if new == old:
        return []
    path = f'/spec/variables/{idx}/expression'
    return [{'op': 'test', 'path': '/metadata/resourceVersion', 'value': obj['metadata']['resourceVersion']},
            {'op': 'test', 'path': path, 'value': old}, {'op': 'replace', 'path': path, 'value': new}]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    obj = json.loads(subprocess.check_output(['kubectl', 'get', 'mutatingadmissionpolicy', POLICY, '-o', 'json']))
    patch = patch_for(obj)
    if patch:
        cmd = ['kubectl', 'patch', 'mutatingadmissionpolicy', POLICY, '--type=json', '-p', json.dumps(patch), '-o', 'name']
        subprocess.run(cmd + ['--dry-run=server'], check=True)
        if args.apply:
            subprocess.run(cmd, check=True)
            print('updated two workload profiles')
