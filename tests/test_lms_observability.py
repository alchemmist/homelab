"""Production LMS telemetry is rendered by Homelab, not a manual dashboard import."""
import importlib.util
import json
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(*args):
    return list(yaml.safe_load_all(subprocess.check_output(
        ['helm', 'template', 'lms', str(ROOT/'charts/lms'), *args], text=True)))


def test_live_values_enable_mtls_without_secret_contents():
    docs = render('-f', str(ROOT/'deploy/lms/values.yaml'))
    dep = next(x for x in docs if x and x['kind']=='Deployment' and x['metadata']['name']=='lms')
    pod = dep['spec']['template']['spec']
    env = {e['name']: e.get('value') for e in pod['containers'][0]['env']}
    assert env['LMS_TRACING_ENABLED']=='1'
    assert env['LMS_TRACE_SAMPLE_RATIO']=='1'
    assert env['OTEL_EXPORTER_OTLP_TRACES_ENDPOINT']=='https://10.250.0.3:44318/v1/traces'
    assert env['OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY']=='/etc/otel-client/tls.key'
    volume = next(x for x in pod['volumes'] if x['name']=='otel-client')
    assert volume['secret']=={'secretName':'otel-app-tls-lms','defaultMode':0o440}
    assert pod['securityContext']['fsGroup']==10001
    assert next(x for x in pod['containers'][0]['volumeMounts'] if x['name']=='otel-client')['readOnly']


def test_dashboard_is_gitops_provisioned_and_uses_real_log_labels():
    docs = render('-f', str(ROOT/'deploy/lms/values.yaml'))
    cm = next(x for x in docs if x and x['kind']=='ConfigMap' and x['metadata']['name']=='lms-performance-dashboard')
    assert cm['metadata']['labels']['grafana_dashboard']=='1'
    dashboard = json.loads(cm['data']['lms-performance.json'])
    assert dashboard['uid']=='lms-performance'
    assert any(p['type']=='traces' for p in dashboard['panels'])
    variable = next(x for x in dashboard['templating']['list'] if x['name']=='log_selector')
    assert variable['current']['value']=='{k8s_namespace_name="lms"}'


def test_disabled_chart_does_not_mount_credentials():
    docs = render('--set', 'tracing.enabled=false')
    dep = next(x for x in docs if x and x['kind']=='Deployment' and x['metadata']['name']=='lms')
    assert not any(x['name']=='otel-client' for x in dep['spec']['template']['spec']['volumes'])


def test_renewal_scope_is_only_lms_leaf_and_lms_deployment():
    docs = list(yaml.safe_load_all((ROOT/'deploy/monitoring/otel-application-credentials.yaml').read_text()))
    role = next(d for d in docs if d['kind']=='Role' and d['metadata']['namespace']=='lms')
    assert role['rules']==[
        {'apiGroups':[''], 'resources':['secrets'], 'resourceNames':['otel-app-tls-lms'], 'verbs':['get','patch']},
        {'apiGroups':['apps'], 'resources':['deployments'], 'resourceNames':['lms'], 'verbs':['get','patch']}]
    source = (ROOT/'scripts/otel-application-credentials.py').read_text()
    spec = importlib.util.spec_from_loader('mirror', loader=None)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(source, 'mirror.py', 'exec'), mod.__dict__)
    mod.validate_destination(dict(application='lms',namespace='lms',secret='otel-app-tls-lms',reloadDeployments=['lms']))
    cm = next(d for d in docs if d['kind']=='ConfigMap')
    assert cm['data']['mirror.py']==source
    lms = next(x for x in json.loads(cm['data']['destinations.json']) if x['application']=='lms')
    assert lms['reloadDeployments']==['lms']
    app = yaml.safe_load((ROOT/'deploy/argocd/apps/lms.yaml').read_text())
    assert 'RespectIgnoreDifferences=true' in app['spec']['syncPolicy']['syncOptions']
    assert app['spec']['ignoreDifferences'][0]['jsonPointers']==['/spec/template/metadata/annotations/homelab.alchemmist.xyz~1client-certificate-sha256']


def test_trace_id_panel_uses_supported_traceql_id_query():
    dashboard = json.loads((ROOT/'charts/lms/files/lms-performance.json').read_text())
    panel = next(x for x in dashboard['panels'] if x['type']=='traces')
    assert panel['targets'][0]['queryType']=='traceql'
    assert panel['targets'][0]['query']=='${trace_id}'


def test_correlations_preserve_credentials_and_survive_refresh():
    spec = importlib.util.spec_from_file_location('correlations', ROOT/'scripts/lms-grafana-correlations.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    document = {'datasources': [
        {'uid': 'loki', 'jsonData': {'tlsAuth': True, 'derivedFields': [{'name':'Other','url':'other'}]},
         'secureJsonData': {'tlsClientKey':'synthetic-private-key'}},
        {'uid':'tempo', 'jsonData': {'tracesToLogsV2': {'datasourceUid':'loki'}}}]}
    result = mod.configure(document)
    assert result['datasources'][0]['secureJsonData']['tlsClientKey']=='synthetic-private-key'
    assert result['datasources'][0]['jsonData']['tlsAuth'] is True
    fields = result['datasources'][0]['jsonData']['derivedFields']
    assert fields[0]['name']=='Other'
    assert fields[-1]['url']=='$${__value.raw}'
    mod.configure(document)
    assert len(result['datasources'][0]['jsonData']['derivedFields'])==2
    for script in ['otel-host-credentials.py', 'otel-production-grafana.py']:
        source = (ROOT/'scripts'/script).read_text()
        assert 'trace_id=([0-9a-f]{32})' in source
        assert '$${__value.raw}' in source
