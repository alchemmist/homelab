"""Exactly the same 77 resources, split between five single-service Applications."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ('prometheus', 'alertmanager', 'prometheus-operator', 'node-exporter', 'kube-state-metrics')
CLUSTER = {'CustomResourceDefinition', 'ClusterRole', 'ClusterRoleBinding', 'MutatingWebhookConfiguration', 'ValidatingWebhookConfiguration'}
yaml.SafeLoader.add_constructor('tag:yaml.org,2002:value', lambda loader, node: loader.construct_scalar(node))

@lru_cache(maxsize=None)
def render(name):
    text = subprocess.check_output(['helm','template','kube-prometheus-stack',str(ROOT/'charts'/name),'-n','cattle-monitoring-system','--include-crds'],text=True)
    return [d for d in yaml.safe_load_all(text) if d and not (d['metadata'].get('annotations') or {}).get('helm.sh/hook')]

def key(d):
    return '/'.join([d['kind'], '' if d['kind'] in CLUSTER else d['metadata'].get('namespace','cattle-monitoring-system'), d['metadata']['name']])

def test_disjoint_complete_payload_identical_handoff():
    fixture=json.loads((ROOT/'tests/fixtures/prometheus-service-handoff.json').read_text())
    actual={}
    for name in COMPONENTS:
        for d in render(name):
            k=key(d)
            assert k not in actual, 'Duplicate owner: '+k
            actual[k]={'owner':name,'sha256':hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    assert len(actual)==77
    assert actual==fixture

def test_each_application_has_only_its_own_runtime():
    runtime={'Prometheus':'prometheus','Alertmanager':'alertmanager','DaemonSet':'node-exporter'}
    for name in COMPONENTS:
        docs=render(name)
        kinds={d['kind'] for d in docs}
        for kind,owner in runtime.items():
            assert (kind in kinds)==(name==owner)
        deps=[d for d in docs if d['kind']=='Deployment']
        assert len(deps)==int(name in ('prometheus-operator','kube-state-metrics'))
        assert ('CustomResourceDefinition' in kinds)==(name=='prometheus-operator')
        if name!='prometheus-operator':
            assert not kinds & {'MutatingWebhookConfiguration','ValidatingWebhookConfiguration'}

def test_offline_source_is_immutable_shared_code_not_shared_ownership():
    archive=ROOT/'charts/_vendor/kube-prometheus-stack-92.10.0.tgz'
    expected=(archive.with_suffix('.sha256')).read_text().split()[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
    for name in COMPONENTS:
        chart=ROOT/'charts'/name
        dep=yaml.safe_load((chart/'Chart.yaml').read_text())['dependencies']
        assert dep==[{'name':'kube-prometheus-stack','version':'92.10.0','repository':'https://prometheus-community.github.io/helm-charts'}]
        link=chart/'charts/kube-prometheus-stack-92.10.0.tgz'
        assert link.is_symlink() and link.resolve()==archive.resolve()
        app=yaml.safe_load((ROOT/f'deploy/argocd/apps/{name}.yaml').read_text())
        assert app['spec']['project']=='default'
        assert app['spec']['source']['path']=='charts/'+name
        assert app['spec']['source']['helm']=={'releaseName':'kube-prometheus-stack','parameters':[]}
        assert app['spec']['syncPolicy']['automated']=={'prune':False,'selfHeal':True}

def test_aggregate_application_and_values_are_gone():
    assert not (ROOT/'deploy/argocd/apps/prometheus-stack.yaml').exists()
    assert not (ROOT/'deploy/platform/prometheus-stack').exists()
