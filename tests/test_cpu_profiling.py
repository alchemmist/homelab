"""CPU profiles are a separate private stack, not renamed tracing spans."""
import json
from pathlib import Path
import subprocess
import yaml
ROOT = Path(__file__).resolve().parents[1]


def render(chart, *args):
    return [d for d in yaml.safe_load_all(subprocess.check_output(['helm','template',chart,str(ROOT/'charts'/chart),*args],text=True)) if d]


def test_backend_is_persistent_bounded_unprivileged_and_private():
    docs=render('profiling')
    dep=next(d for d in docs if d['kind']=='Deployment')
    pod=dep['spec']['template']['spec']; c=pod['containers'][0]
    assert pod['automountServiceAccountToken'] is False
    assert pod['securityContext']['runAsNonRoot'] is True
    assert c['securityContext']['capabilities']['drop']==['ALL']
    assert c['securityContext']['readOnlyRootFilesystem'] is True
    assert c['securityContext']['allowPrivilegeEscalation'] is False
    assert '@sha256:' in c['image']
    assert '-architecture.storage=v2' in c['args']
    assert '-retention-period=168h' in c['args']
    assert '-usage-stats.enabled=false' in c['args']
    assert c['resources']['limits']['memory']=='1Gi'
    assert c['workingDir']=='/data'
    assert any(d['kind']=='PersistentVolumeClaim' for d in docs)
    service=next(d for d in docs if d['kind']=='Service')
    assert service['spec']['type']=='ClusterIP'
    assert not any(d['kind']=='Ingress' for d in docs)
    policy=next(d for d in docs if d['kind']=='NetworkPolicy')['spec']
    assert set(policy['policyTypes'])=={'Ingress','Egress'}
    assert policy['ingress'][0]['ports']==[{'protocol':'TCP','port':4040}]
    peers=policy['ingress'][0]['from']
    assert {p['podSelector']['matchLabels']['app.kubernetes.io/name'] for p in peers}=={'lms','grafana'}
    assert all('namespaceSelector' in p for p in peers)


def test_flamegraph_is_native_pyroscope_not_a_span_waterfall():
    docs=render('profiling')
    cm=next(d for d in docs if d['metadata']['name']=='service-cpu-profiling-dashboard')
    d=json.loads(cm['data']['service-cpu-profiling.json'])
    assert d['uid']=='service-cpu-profiling'
    assert d['panels'][0]['type']=='flamegraph'
    assert d['panels'][1]['type']=='timeseries'
    assert not any(p['type']=='traces' for p in d['panels'])
    for panel in d['panels']:
        assert panel['datasource']['uid']=='pyroscope'
        assert panel['targets'][0]['profileTypeId']=='process_cpu:cpu:nanoseconds:cpu:nanoseconds'
    assert d['templating']['list'][0]['query']['labelName']=='service_name'
    source=next(x for x in docs if x['metadata']['name']=='pyroscope-grafana-datasource')
    ds=yaml.safe_load(source['data']['pyroscope-datasource.yaml'])['datasources'][0]
    assert ds['uid']=='pyroscope' and ds['editable'] is False
    assert ds['url']=='http://pyroscope.cattle-monitoring-system.svc.cluster.local:4040'


def test_lms_profiling_is_opt_in_and_production_enabled():
    for args,enabled in [((),False),(('-f',str(ROOT/'deploy/lms/values.yaml')),True)]:
        docs=render('lms',*args)
        dep=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='lms')
        env={e['name']:e.get('value') for e in dep['spec']['template']['spec']['containers'][0]['env']}
        assert (env.get('LMS_PROFILING_ENABLED')=='1')==enabled
        if enabled:assert env['LMS_PROFILING_ENDPOINT'].endswith('.svc.cluster.local:4040')
