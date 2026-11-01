"""Conservative gate for a single-node IdP; reserves existing OTel plan headroom."""
from decimal import Decimal
import json
import os
import subprocess

def quantity(x):
    for unit,mul in [('Ki',1024),('Mi',1024**2),('Gi',1024**3),('M',1000**2),('G',1000**3),('m',.001)]:
        if str(x).endswith(unit):return int(Decimal(str(x)[:-len(unit)])*Decimal(str(mul)))
    return int(Decimal(str(x)))

kube=['kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml']
node=json.loads(subprocess.check_output(kube+['get','node','socrat-0','-o','json'],text=True))
pods=json.loads(subprocess.check_output(kube+['get','pods','-A','--field-selector=spec.nodeName=socrat-0','-o','json'],text=True))
mem=dict(x.split(':',1) for x in open('/proc/meminfo'))
available=int(mem['MemAvailable'].split()[0])*1024
requests=0
for pod in pods['items']:
    if pod.get('status',{}).get('phase') in ['Succeeded','Failed']:continue
    spec=pod['spec']
    requests+=sum(quantity(c.get('resources',{}).get('requests',{}).get('memory',0)) for c in spec.get('containers',[])+spec.get('initContainers',[]))
    requests+=quantity(spec.get('overhead',{}).get('memory',0))
free=quantity(node['status']['allocatable']['memory'])-requests
conditions={x['type']:x['status'] for x in node['status']['conditions']}
if node['spec'].get('unschedulable') or conditions.get('Ready')!='True' or any(conditions.get(x)!='False' for x in ['MemoryPressure','DiskPressure','PIDPressure']):
    raise SystemExit('Node is not healthy/schedulable')
# 1792 MiB app requests, 2304 MiB outstanding OTel envelope, 2048 MiB host reserve.
if available < (1792+2304+2048)*1024**2 or free < (1792+2304)*1024**2:
    raise SystemExit('Insufficient memory for identity staging and reserved OTel budget')
disk=os.statvfs('/var/lib/rancher/k3s/storage')
if disk.f_bavail*disk.f_frsize < 30*1024**3:raise SystemExit('Insufficient storage staging reserve')
print('Capacity gate passed: single-node identity staging only, not HA certification')
