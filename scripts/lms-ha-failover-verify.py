#!/usr/bin/env python3
"""Staging-only failover test: cordon primary's node, gracefully delete its pod.

Always restores the original schedulable state. Does not power off any node or
claim a network-partition test. Refuses when the web app already uses the HA DB.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import shlex
import time
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('verify',ROOT/'scripts/lms-observability-verify.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)


def kube(*args):
    r=subprocess.run(['ssh','-o','BatchMode=yes','socrat-0',shlex.join(['kubectl',*args])],capture_output=True,text=True,timeout=90)
    if r.returncode:raise RuntimeError('Failover verification Kubernetes operation failed: '+r.stderr[-500:])
    return r.stdout


host=helper.kubepython('''
from app.config import Settings
from urllib.parse import urlsplit
import json
print(json.dumps(dict(host=urlsplit(Settings.from_env().database_url).hostname)))
''')['host']
if host not in {'lms-postgres','lms-postgres.lms.svc.cluster.local'}:raise RuntimeError('Staging-only test refused: production is not on legacy endpoint')
cluster=json.loads(kube('-n','lms','get','cluster.postgresql.cnpg.io/lms-ha','-o','json'))
if cluster['status'].get('readyInstances')!=3:raise RuntimeError('Require three healthy instances')
old=cluster['status']['currentPrimary']
pod=json.loads(kube('-n','lms','get','pod',old,'-o','json'));node=pod['spec']['nodeName']
if json.loads(kube('get','node',node,'-o','json'))['spec'].get('unschedulable'):raise RuntimeError('Refusing to modify already cordoned node')
kube('-n','lms','exec',old,'--','psql','-U','postgres','-d','lms','-c','CREATE SCHEMA ha_probe; CREATE TABLE ha_probe.marker (id integer PRIMARY KEY); INSERT INTO ha_probe.marker VALUES (42);')
began=time.monotonic()
new=None
try:
    kube('cordon',node)
    kube('-n','lms','delete','pod',old,'--wait=true','--timeout=60s')
    for attempt in range(40):
        c=json.loads(kube('-n','lms','get','cluster.postgresql.cnpg.io/lms-ha','-o','json'))
        candidate=c['status'].get('currentPrimary')
        if candidate and candidate!=old:
            try:
                marker=kube('-n','lms','exec',candidate,'--','psql','-U','postgres','-d','lms','-Atc','SELECT id FROM ha_probe.marker;')
                if marker.strip()=='42':
                    kube('-n','lms','exec',candidate,'--','psql','-U','postgres','-d','lms','-c','INSERT INTO ha_probe.marker VALUES (43);')
                    new=candidate
                    break
            except RuntimeError:pass
        time.sleep(3)
    if not new:raise RuntimeError('Primary replacement / acknowledged-data probe timed out')
    elapsed=round(time.monotonic()-began,2)
finally:
    kube('uncordon',node)
if new:kube('-n','lms','exec',new,'--','psql','-U','postgres','-d','lms','-c','DROP SCHEMA ha_probe CASCADE;')
report={'verifiedAt':datetime.now(timezone.utc).isoformat(),'success':True,'test':'staging primary pod deletion while its node is cordoned','oldPrimary':old,'newPrimary':new,'oldPrimaryNode':node,'failoverAndWriteProbeSeconds':elapsed,'acknowledgedMarkerPreserved':True,'newPrimaryWriteSucceeded':True,'nodeUncordoned':True,'powerLossOrNetworkPartitionTested':False}
p=ROOT/'deploy/monitoring/migration-evidence/lms-postgres-staged-failover-20261103.json';p.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
