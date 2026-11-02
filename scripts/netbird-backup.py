#!/usr/bin/env python3
"""Quiesced SQLite copy plan for the single NetBird control-plane replica.

A live file copy is not a consistent backup. v0.82.0 combined server has one
SQLite writer and this is not management HA. The copy pod mounts the PVC
read-only, does not mount the runtime secret, and is not applied unless the
confirmation phrase is supplied. Keys must be backed up separately and never printed.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONFIRM = 'quiesce-netbird-sqlite'
FILES = ['store.db', 'store.db-wal', 'store.db-shm', 'events.db', 'events.db-wal', 'events.db-shm',
         'idp.db', 'idp.db-wal', 'idp.db-shm', 'access_logs.db', 'access_logs.db-wal', 'access_logs.db-shm']


def require(ok, message):
    if not ok:
        raise ValueError(message)


def copy_pod(node, image, read_only):
    require(isinstance(node, str) and node and '/' not in node and '..' not in node, 'explicit data node required')
    require(isinstance(image, str) and '@sha256:' in image, 'pinned server image required')
    return {
        'apiVersion': 'v1', 'kind': 'Pod',
        'metadata': {'name': 'netbird-sqlite-copy', 'namespace': 'netbird-pilot'},
        'spec': {
            'restartPolicy': 'Never', 'automountServiceAccountToken': False,
            'nodeSelector': {'kubernetes.io/hostname': node},
            'containers': [{
                'name': 'copy', 'image': image, 'imagePullPolicy': 'IfNotPresent',
                'command': ['sleep', '600'],
                'volumeMounts': [{'name': 'data', 'mountPath': '/var/lib/netbird', 'readOnly': read_only}]}],
            'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'server-data'}}]}}


def plan(node, image):
    pod = copy_pod(node, image, True)
    blob = json.dumps(pod)
    require('secret' not in blob and 'NB_' not in blob, 'backup pod must not carry credentials')
    return {
        'quiesce_required': True,
        'management_ha': False,
        'reason': 'Stop the single server so SQLite closes its WAL, then copy from a read-only pod. '
                  'Do not copy a live database. Restore needs the same store and cookie keys.',
        'directory': '/var/lib/netbird',
        'files': FILES,
        'pod': pod,
        'commands': [
            ['kubectl', '-n', 'netbird-pilot', 'scale', 'deploy/server', '--replicas=0'],
            ['kubectl', '-n', 'netbird-pilot', 'apply', '-f', 'sqlite-copy-pod.yaml'],
            ['kubectl', '-n', 'netbird-pilot', 'cp', 'netbird-sqlite-copy:/var/lib/netbird/.', 'DEST'],
            ['kubectl', '-n', 'netbird-pilot', 'delete', 'pod', 'netbird-sqlite-copy', '--wait=true'],
            ['kubectl', '-n', 'netbird-pilot', 'scale', 'deploy/server', '--replicas=1']]}


def outside(path):
    require(path is not None, '--out required')
    require(not path.resolve().is_relative_to(ROOT), '--out must be outside the Git worktree')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['plan', 'execute'])
    p.add_argument('--node', required=True)
    p.add_argument('--image', required=True)
    p.add_argument('--out', type=Path)
    p.add_argument('--confirm', default='')
    a = p.parse_args()
    outside(a.out)
    body = plan(a.node, a.image)
    a.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = a.out / 'sqlite-copy-pod.yaml'
    # Local import keeps the plan free of a rendered secret.
    import yaml
    manifest.write_text(yaml.safe_dump(body['pod'], sort_keys=False))
    (a.out / 'plan.json').write_text(json.dumps({k: v for k, v in body.items() if k != 'pod'}, indent=2) + '\n')
    manifest.chmod(0o600)
    if a.command == 'plan':
        print('Backup plan written; server was not scaled and kubectl was not run')
        return
    require(a.confirm == CONFIRM, 'backup confirmation phrase mismatch')
    commands = body['commands']
    commands[1] = ['kubectl', '-n', 'netbird-pilot', 'apply', '-f', str(manifest)]
    commands[2] = ['kubectl', '-n', 'netbird-pilot', 'cp', 'netbird-sqlite-copy:/var/lib/netbird/.', str(a.out / 'data')]
    for argv in commands:
        subprocess.run(argv, check=True)
    print('Quiesced copy finished; encryption keys were not printed')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print('BLOCKED: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        sys.exit(2)
