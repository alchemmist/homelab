#!/usr/bin/env python3
"""Render (never apply) the explicit owner-admin one-shot DNS renderer delta.

Only adds the approved name to the existing renderer after an exact SHA guard.
Uses existing installer-Job pattern, but needs no host PID, chroot, privileged
container, SSH or sudo changes. Writable mount is the managed libexec directory
for atomic rename; code touches only public_dns_zone.py and its unique tempfile.
Capture a fresh private baseline before apply. Never retry after a hash mismatch.
"""
import argparse
import json
from pathlib import Path
import yaml
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--expected-sha256', required=True)
p.add_argument('--node', required=True, choices=['socrat-0', 'socrat-1', 'socrat-2'])
a=p.parse_args()
assert len(a.expected_sha256)==64 and all(c in '0123456789abcdef' for c in a.expected_sha256)
root=Path(__file__).resolve().parents[1]
image=yaml.safe_load((root/'charts/x-ui/values.yaml').read_text())['instances']['primary']['image']
code='''import hashlib,os,pathlib,tempfile
p=pathlib.Path('/managed/public_dns_zone.py')
assert not p.is_symlink()
raw=p.read_bytes()
assert hashlib.sha256(raw).hexdigest()==EXPECTED, 'concurrent change: stop, no overwrite'
s=raw.decode()
old='    "n8n.socrat",\\n'
new=old+'    "netbird.socrat",\\n'
assert s.count(old)==1 and '"netbird.socrat"' not in s
updated=s.replace(old,new)
compile(updated,str(p),'exec')
stat=p.stat()
fd,name=tempfile.mkstemp(prefix='.public_dns_zone.netbird-',dir=p.parent)
try:
 with os.fdopen(fd,'w') as f:
  f.write(updated);f.flush();os.fsync(f.fileno())
 os.chmod(name,stat.st_mode & 0o777)
 assert hashlib.sha256(p.read_bytes()).hexdigest()==EXPECTED, 'concurrent change: stop'
 os.replace(name,p)
 print('Only approved netbird.socrat added; new SHA256='+hashlib.sha256(p.read_bytes()).hexdigest())
finally:
 if os.path.exists(name):os.unlink(name)
'''
job={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'netbird-dns-renderer-delta-'+a.node,'namespace':'identity'},'spec':{'backoffLimit':0,'activeDeadlineSeconds':120,'ttlSecondsAfterFinished':3600,'template':{'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,'nodeSelector':{'kubernetes.io/hostname':a.node},'containers':[{'name':'delta','image':image,'command':['python3','-c','EXPECTED='+repr(a.expected_sha256)+'\n'+code],'securityContext':{'runAsUser':0,'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},'resources':{'requests':{'cpu':'10m','memory':'32Mi'},'limits':{'cpu':'200m','memory':'96Mi'}},'volumeMounts':[{'name':'managed','mountPath':'/managed'}]}],'volumes':[{'name':'managed','hostPath':{'path':'/usr/local/libexec','type':'Directory'}}]}}}}
print(json.dumps(job))
