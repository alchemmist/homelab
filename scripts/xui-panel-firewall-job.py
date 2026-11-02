#!/usr/bin/env python3
"""Render the explicit owner-admin one-shot host firewall installer; does not apply.
Only socrat-2, SYS_CHROOT, host PID visibility and two writable managed directories.
Do not run as an unreviewed routine workload. No SSH/sudo policy is modified.
"""
from pathlib import Path
import yaml,json
ROOT=Path(__file__).resolve().parents[1]
rules=(ROOT/'deploy/xui-auth-gateway-host/rules.nft').read_text();unit=(ROOT/'deploy/xui-auth-gateway-host/homelab-xui-panel-auth.service').read_text()
code='''import os,pathlib,subprocess
os.environ['SYSTEMD_IGNORE_CHROOT']='1'
def host(args):
 r=subprocess.run(['chroot','/host']+args,capture_output=True,text=True)
 if r.returncode:raise RuntimeError('Host operation failed: '+args[0]+' '+r.stderr[:500])
 return r.stdout
# Existing native systemd is contacted through the read-only host /run socket.
# No SSH/sudo policy change and no x-ui/Xray process command.
print('Host systemd reachable:',host(['/usr/bin/systemctl','show','--property=Version']).strip())
unit_path=pathlib.Path('/host/etc/systemd/system/homelab-xui-panel-auth.service')
if unit_path.exists() and unit_path.read_text()!=UNIT:raise RuntimeError('Unmanaged existing service; refusing overwrite')
pathlib.Path('/host/etc/xui-panel-auth/rules.nft').write_text(RULES)
os.chmod('/host/etc/xui-panel-auth/rules.nft',0o600)
unit_path.write_text(UNIT);os.chmod(unit_path,0o644)
host(['/usr/bin/systemctl','daemon-reload'])
host(['/usr/bin/systemctl','enable','--now','homelab-xui-panel-auth.service'])
host(['/usr/bin/systemctl','reload-or-restart','homelab-xui-panel-auth.service'])
print('Panel-only firewall service:',host(['/usr/bin/systemctl','is-active','homelab-xui-panel-auth.service']).strip())
'''
code='UNIT='+repr(unit)+'\nRULES='+repr(rules)+'\n'+code
j={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'xui-panel-firewall-install','namespace':'traefik-edge'},'spec':{'backoffLimit':0,'ttlSecondsAfterFinished':3600,'template':{'spec':{'restartPolicy':'Never','hostPID':True,'automountServiceAccountToken':False,'nodeSelector':{'kubernetes.io/hostname':'socrat-2'},'containers':[{'name':'install','image':yaml.safe_load((ROOT/'charts/x-ui/values.yaml').read_text())['instances']['primary']['image'],'command':['python3','-c',code],'securityContext':{'runAsUser':0,'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL'],'add':['SYS_CHROOT']}},'resources':{'requests':{'cpu':'10m','memory':'32Mi'},'limits':{'cpu':'200m','memory':'96Mi'}},'volumeMounts':[{'name':'host','mountPath':'/host','readOnly':True},{'name':'units','mountPath':'/host/etc/systemd/system'},{'name':'rules','mountPath':'/host/etc/xui-panel-auth'}]}],'volumes':[{'name':'host','hostPath':{'path':'/','type':'Directory'}},{'name':'units','hostPath':{'path':'/etc/systemd/system','type':'Directory'}},{'name':'rules','hostPath':{'path':'/etc/xui-panel-auth','type':'DirectoryOrCreate'}}]}}}}
print(json.dumps(j))
