#!/usr/bin/env python3
"""Read-only PV/mount inventory. Never creates pods, reads datasets or uses sudo."""
import argparse
import datetime
import json
import subprocess


def run(args, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, timeout=120, **kwargs)


def kub(resource):
    result = run(['kubectl', 'get', resource, '-A', '-o', 'json'])
    result.check_returncode()
    return json.loads(result.stdout)['items']


def inventory(pvs, pods):
    rows = []
    for pv in pvs:
        spec = pv['spec']
        claim = spec.get('claimRef', {})
        consumers = []
        for pod in pods:
            if pod['metadata']['namespace'] != claim.get('namespace'):
                continue
            if any(v.get('persistentVolumeClaim', {}).get('claimName') == claim.get('name')
                   for v in pod['spec'].get('volumes', [])):
                consumers.append({'pod': pod['metadata']['name'], 'node': pod['spec'].get('nodeName')})
        terms = spec.get('nodeAffinity', {}).get('required', {}).get('nodeSelectorTerms', [])
        nodes = sorted({n for term in terms for e in term.get('matchExpressions', [])
                        if e['key'] == 'kubernetes.io/hostname' and e['operator'] == 'In'
                        for n in e['values']})
        backend = spec.get('local') or spec.get('hostPath') or spec.get('nfs') or {}
        rows.append({'pv': pv['metadata']['name'], 'claim': claim, 'phase': pv.get('status', {}).get('phase'),
                     'class': spec.get('storageClassName', ''), 'requested_capacity': spec['capacity'],
                     'reclaim': spec['persistentVolumeReclaimPolicy'], 'nodes': nodes,
                     'backend': backend, 'consumers': consumers})
    return rows


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--node', default='socrat-5', choices=[f'socrat-{i}' for i in range(6)])
    args = parser.parse_args()
    rows = inventory(kub('pv'), kub('pods'))
    paths = sorted({r['backend']['path'] for r in rows if args.node in r['nodes'] and 'path' in r['backend']})
    # Fixed remote program; paths travel as JSON on stdin, never interpolated into shell.
    remote = """import json,sys,subprocess,os
paths=json.load(sys.stdin)
mounts=subprocess.run(['findmnt','-rn','-o','TARGET,SOURCE,FSTYPE'],text=True,capture_output=True,check=True).stdout.splitlines()
mounts=[dict(zip(['target','source','fstype'],line.split())) for line in mounts if len(line.split())==3]
out=[]
for path in paths:
 r=subprocess.run(['findmnt','-J','-T',path,'-o','TARGET,SOURCE,FSTYPE,OPTIONS'],text=True,capture_output=True)
 d=subprocess.run(['du','-sx','--block-size=1',path],text=True,capture_output=True,timeout=60)
 candidates=[m for m in mounts if path==m['target'] or path.startswith(m['target'].rstrip('/')+'/')]
 inferred=max(candidates,key=lambda m:len(m['target'])) if candidates else None
 item={'mount_table_resolution':inferred,'resolution_note':'mount-table longest-prefix; not canonical path proof when stat is denied','path':path,'mount':json.loads(r.stdout) if r.returncode==0 else None,'mount_complete':r.returncode==0,'du_complete':d.returncode==0,'used_bytes':int(d.stdout.split()[0]) if d.returncode==0 else None}
 try:
  s=os.statvfs(path);item['filesystem']={'capacity_bytes':s.f_blocks*s.f_frsize,'available_bytes':s.f_bavail*s.f_frsize,'inodes':s.f_files,'inodes_free':s.f_favail}
 except OSError as e:item['stat_error']=str(e)
 out.append(item)
print(json.dumps(out))"""
    result = run(['ssh', '-o', 'BatchMode=yes', args.node, 'python3 -c ' + __import__('shlex').quote(remote)],
                 input=json.dumps(sorted(set(paths + ['/', '/mnt/files', '/var/lib/rancher/k3s', '/var/lib/containerd', '/var/log', '/home']))))
    result.check_returncode()
    print(json.dumps({'observed_at': datetime.datetime.now(datetime.UTC).isoformat(), 'node': args.node,
                      'pvs': rows, 'mount_inspection': json.loads(result.stdout),
                      'storage_classes': kub('storageclasses'),
                      'limitations': ['du failures are unknown, never zero', 'PVC capacity is not a directory quota',
                                      'No dataset contents read; root-only disk usage requires operator measurement']}, indent=2))


if __name__ == '__main__':
    main()
