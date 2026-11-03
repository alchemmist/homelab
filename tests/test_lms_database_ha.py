import json
from pathlib import Path
import subprocess
import yaml
ROOT=Path(__file__).resolve().parents[1]


def rendered(chart,*args):
    return [d for d in yaml.safe_load_all(subprocess.check_output(['helm','template',chart,str(ROOT/'charts'/chart),*args],text=True)) if d]


def test_database_has_three_separate_failure_domains_and_required_sync_quorum():
    docs=rendered('lms-database-ha')
    c=next(d for d in docs if d['kind']=='Cluster')['spec']
    assert c['instances']==3
    assert c['postgresql']['synchronous']=={'method':'any','number':1,'dataDurability':'required','failoverQuorum':True}
    assert c['postgresql']['parameters']['synchronous_commit']=='on'
    assert c['affinity']['podAntiAffinityType']=='required'
    assert c['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0]['matchExpressions'][0]['values']==['socrat-0','socrat-1','socrat-3']
    assert c['storage']['storageClass']=='lms-db-retain'
    sc=next(d for d in docs if d['kind']=='StorageClass')
    assert sc['reclaimPolicy']=='Retain'
    assert '@sha256:' in c['imageName'] and ':17.11-' in c['imageName']
    assert c['enableSuperuserAccess'] is False


def test_backups_are_encrypted_and_not_shared_plaintext_files():
    docs=rendered('lms-database-ha','--set','backup.enabled=true')
    cron=next(d for d in docs if d['kind']=='CronJob')
    assert cron['spec']['concurrencyPolicy']=='Forbid'
    spec=cron['spec']['jobTemplate']['spec']['template']['spec']
    assert spec['automountServiceAccountToken'] is False
    cmd=spec['containers'][0]['args'][0]
    assert 'umask 077' in cmd and '--symmetric --cipher-algo AES256' in cmd
    assert '--passphrase-file /backup-key/passphrase' in cmd
    assert 'PGSSLMODE=verify-full' in cmd
    assert 'cmp /tmp/database.dump /tmp/checked.dump' in cmd
    assert "-name 'scheduled-*.dump.gpg'" in cmd
    assert next(v for v in spec['volumes'] if v['name']=='tmp')['emptyDir']['medium']=='Memory'


def test_single_worker_recreate_and_bounded_node_eviction_are_preserved():
    docs=rendered('lms','--set','database.ha.enabled=true')
    dep=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='lms')
    assert dep['spec']['replicas']==1 and dep['spec']['strategy']['type']=='Recreate'
    pod=dep['spec']['template']['spec']
    assert {t['tolerationSeconds'] for t in pod['tolerations']}=={60}
    ca=next(v for v in pod['volumes'] if v['name']=='postgres-ca')['secret']
    assert ca['items']==[{'key':'ca.crt','path':'ca.crt'}]
    assert ca['defaultMode']==288


def test_copy_tool_refuses_live_ha_overwrite_and_final_restore_without_freeze():
    s=(ROOT/'scripts/lms-ha-copy.py').read_text()
    assert "application no longer uses legacy DB" in s
    assert "if dep['spec']['replicas']!=0 or pods['items']" in s
    assert "'backoffLimit':0" in s
    assert "shlex.join(['kubectl',*args])" in s
    copy=(ROOT/'scripts/lms-ha/copy-database.sh').read_text()
    assert 'cmp /tmp/source.dump /tmp/recovered.dump' in copy
    assert 'cmp /tmp/source.fingerprint /tmp/target.fingerprint' in copy
    assert '--single-transaction' in copy and 'PGSSLMODE=verify-full' in copy
