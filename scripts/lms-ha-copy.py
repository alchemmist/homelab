#!/usr/bin/env python3
"""Run a guarded private pg_dump/restore Job; never print credentials or dump data."""
import argparse
import base64
from urllib.parse import urlsplit
import json
from pathlib import Path
import subprocess
import shlex
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]


def kube(*args, document=None):
    r=subprocess.run(['ssh','-o','BatchMode=yes','socrat-0',shlex.join(['kubectl',*args])],input=json.dumps(document) if document else None,capture_output=True,text=True,timeout=180)
    if r.returncode:raise RuntimeError('Kubernetes operation failed: '+r.stderr[-1500:])
    return r.stdout


def run(args):
    secret=json.loads(kube('-n','lms','get','secret','lms-db','-o','json'))
    try:
        host=urlsplit(base64.b64decode(secret['data']['LMS_DATABASE_URL'], validate=True).decode()).hostname
    except (KeyError, ValueError, UnicodeError):
        raise ValueError('Refusing restore: application database endpoint cannot be verified') from None
    if host not in {'lms-postgres','lms-postgres.lms.svc.cluster.local'}:
        raise ValueError('Refusing to overwrite HA database: application no longer uses legacy DB')
    if not args.rehearsal and not args.confirm_web_stopped:
        raise ValueError('Final copy requires --confirm-web-stopped')
    if not args.rehearsal:
        dep=json.loads(kube('-n','lms','get','deployment','lms','-o','json'))
        pods=json.loads(kube('-n','lms','get','pods','-l','app.kubernetes.io/name=lms','-o','json'))
        if dep['spec']['replicas']!=0 or pods['items']:
            raise ValueError('Refusing final restore: LMS is not fully stopped')
    name='lms-ha-copy-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    script=(ROOT/'scripts/lms-ha/copy-database.sh').read_text()
    job={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':name,'namespace':'lms'},'spec':{'backoffLimit':0,'activeDeadlineSeconds':180,'ttlSecondsAfterFinished':86400,'template':{'metadata':{'labels':{'app.kubernetes.io/name':'lms-ha-copy'}},'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,'securityContext':{'runAsUser':999,'runAsGroup':999,'fsGroup':999},'containers':[{'name':'copy','image':'docker.io/library/postgres@sha256:839fbb5a4942a7758dd93e18b42ea5649807491a0545b5eeeb8f0b8bb11857a5','command':['sh','-c',script],'env':[{'name':'SOURCE_PASSWORD','valueFrom':{'secretKeyRef':{'name':'lms-db','key':'POSTGRES_PASSWORD'}}},{'name':'TARGET_PASSWORD','valueFrom':{'secretKeyRef':{'name':'lms-ha-app','key':'password'}}},{'name':'BACKUP_ID','value':name},{'name':'REQUIRE_EXACT_MATCH','value':'0' if args.rehearsal else '1'}],'resources':{'requests':{'cpu':'50m','memory':'64Mi'},'limits':{'memory':'256Mi'}},'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},'volumeMounts':[{'name':'backups','mountPath':'/backups'},{'name':'ca','mountPath':'/etc/postgres-ca','readOnly':True},{'name':'tmp','mountPath':'/tmp'},{'name':'backup-key','mountPath':'/backup-key','readOnly':True}]}],'volumes':[{'name':'backups','persistentVolumeClaim':{'claimName':'lms-database-backups'}},{'name':'ca','secret':{'secretName':'lms-ha-ca','items':[{'key':'ca.crt','path':'ca.crt'}]}},{'name':'tmp','emptyDir':{'medium':'Memory','sizeLimit':'128Mi'}},{'name':'backup-key','secret':{'secretName':'lms-backup-key','defaultMode':288}}]}}}}
    kube('create','-f','-',document=job)
    import time
    try:
        for attempt in range(60):
            status=json.loads(kube('-n','lms','get','job',name,'-o','json')).get('status',{})
            if status.get('succeeded'):break
            if status.get('failed'):raise RuntimeError('Copy job failed; production endpoint not changed')
            time.sleep(2)
        else:raise RuntimeError('Copy job timed out')
    finally:
        logs=kube('-n','lms','logs','job/'+name)
        for line in logs.splitlines():
            if line.startswith(('fingerprintDifferenceTable=','sourceFingerprintSHA256=','fingerprintMismatch=','backupSHA256=','logicalDataFingerprintMatched=','rehearsalRestoreCompleted=','targetFingerprintSHA256=','tlsVerified=','restoreFailed=')): print(line)
    print(json.dumps({'job':name,'rehearsal':args.rehearsal,'backupPath':'/backups/lms/'+name+'.dump.gpg','secretsPrinted':False}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rehearsal',action='store_true')
    p.add_argument('--confirm-web-stopped',action='store_true')
    run(p.parse_args())
