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
    assert spec['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0]['matchExpressions'][0]['values']==['socrat-0','socrat-1']
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
    assert 'COLLATE "C"' in copy
    assert 'fingerprintMismatch=true; exit 1' in copy


def test_database_is_a_source_of_the_lms_application():
    app=yaml.safe_load((ROOT/'deploy/argocd/apps/lms.yaml').read_text())
    assert 'sources' not in app['spec']
    assert app['spec']['source']['path']=='charts/lms'
    assert app['spec']['source']['helm']['releaseName']=='lms'
    assert not (ROOT/'deploy/argocd/apps/lms-database-ha.yaml').exists()


def test_runtime_credentials_are_preserved_across_argo_sync():
    app=yaml.safe_load((ROOT/'deploy/argocd/apps/lms.yaml').read_text())
    assert 'RespectIgnoreDifferences=true' in app['spec']['syncPolicy']['syncOptions']
    assert any(rule.get('kind')=='Secret' and rule.get('name')=='lms-db' and rule.get('jsonPointers')==['/data'] for rule in app['spec']['ignoreDifferences'])
    secret=next(d for d in rendered('lms') if d['kind']=='Secret' and d['metadata']['name']=='lms-db')
    assert 'data' not in secret
    assert 'lookup' not in (ROOT/'charts/lms/templates/database.yaml').read_text()


def test_production_web_does_not_depend_on_legacy_nfs_and_legacy_db_is_stopped():
    docs=rendered('lms','-f',str(ROOT/'deploy/lms/values.yaml'))
    web=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='lms')
    assert not any('persistentVolumeClaim' in volume for volume in web['spec']['template']['spec']['volumes'])
    assert any(d['kind']=='PersistentVolumeClaim' and d['metadata']['name']=='lms-data' for d in docs)
    old=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='lms-postgres')
    assert old['spec']['replicas']==1


def test_operator_canary_avoids_stale_ready_pod_on_unreachable_node():
    import importlib.util
    import pytest
    spec=importlib.util.spec_from_file_location('verify',ROOT/'scripts/lms-observability-verify.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    def pod(name,node,deleting=False):
        return {'metadata':{'name':name,**({'deletionTimestamp':'now'} if deleting else {})},'spec':{'nodeName':node},'status':{'phase':'Running','conditions':[{'type':'Ready','status':'True'}]}}
    nodes={'items':[{'metadata':{'name':n},'status':{'conditions':[{'type':'Ready','status':ready}]}} for n,ready in [('socrat-3','Unknown'),('socrat-1','True')]]}
    assert module.ready_canary_pod({'items':[pod('old','socrat-3',True),pod('new','socrat-1')]},nodes)=='new'
    with pytest.raises(RuntimeError):module.ready_canary_pod({'items':[pod('old','socrat-3')]},nodes)


def test_remote_canary_programs_are_valid_python_including_finally_cleanup():
    import ast
    for filename in ['lms-cpu-profile-verify.py','lms-observability-verify.py']:
        tree=ast.parse((ROOT/'scripts'/filename).read_text())
        snippets=[n for n in ast.walk(tree) if isinstance(n,ast.JoinedStr) and any(isinstance(v,ast.Constant) and 'from app.config import Settings' in str(v.value) for v in n.values)]
        assert snippets
        for node in snippets:
            program=''.join(v.value if isinstance(v,ast.Constant) else repr('synthetic-canary') for v in node.values)
            ast.parse(program)


def test_copy_refuses_live_ha_or_unknown_endpoint_before_creating_job(monkeypatch):
    import base64
    import importlib.util
    import json
    from types import SimpleNamespace
    import pytest
    spec=importlib.util.spec_from_file_location('ha_copy',ROOT/'scripts/lms-ha-copy.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for data in [
        {'LMS_DATABASE_URL':base64.b64encode(b'postgresql://example@lms-ha-rw.lms.svc.cluster.local/lms').decode()},
        {},
        {'LMS_DATABASE_URL':'invalid-base64!'},
        {'LMS_DATABASE_URL':base64.b64encode(b'').decode()},
    ]:
        calls=[]
        def kube(*args, **kwargs):
            calls.append(args)
            assert args==('-n','lms','get','secret','lms-db','-o','json')
            return json.dumps({'data':data})
        monkeypatch.setattr(module,'kube',kube)
        with pytest.raises(ValueError,match='Refusing'):
            module.run(SimpleNamespace(rehearsal=True,confirm_web_stopped=True))
        assert len(calls)==1
