"""Monitoring ownership contracts; no image, data path, TLS or selector migration."""
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
NS = 'cattle-monitoring-system'
CLUSTER = {'ClusterRole', 'ClusterRoleBinding', 'CustomResourceDefinition', 'MutatingWebhookConfiguration', 'ValidatingWebhookConfiguration'}
COMPONENTS = ('prometheus', 'alertmanager', 'prometheus-operator', 'node-exporter', 'kube-state-metrics')
yaml.SafeLoader.add_constructor('tag:yaml.org,2002:value', lambda loader, node: loader.construct_scalar(node))
OWNERS = {'grafana': ('charts/grafana', 'kube-prometheus-stack'), 'loki': ('charts/loki', 'loki'), 'tempo': ('charts/tempo', 'tempo'), 'pyroscope': ('charts/pyroscope', 'profiling'), 'monitoring-k3s': ('charts/monitoring-k3s', 'monitoring-k3s')}

OWNERS.update({name: ('charts/'+name, 'kube-prometheus-stack') for name in COMPONENTS})

@lru_cache(maxsize=None)

def render(path, release):
    text = subprocess.check_output(['helm', 'template', release, str(ROOT/path), '-n', NS, '--include-crds'], text=True)
    return [d for d in yaml.safe_load_all(text) if d and not (d['metadata'].get('annotations') or {}).get('helm.sh/hook')]

def key(d):
    return '/'.join([d['kind'], '' if d['kind'] in CLUSTER else d['metadata'].get('namespace', NS), d['metadata']['name']])

def digest(d):
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def normalized(d):
    d = json.loads(json.dumps(d))
    name = d['metadata']['name']
    if d['kind'] == 'Deployment' and name == 'kube-prometheus-stack-grafana':
        d['spec']['template']['metadata']['annotations'].pop('checksum/config', None)
        for c in d['spec']['template']['spec']['containers']:
            c['env'] = [e for e in c.get('env', []) if not e['name'].startswith('GF_AUTH_')]
    if d['kind'] == 'ConfigMap' and name == 'kube-prometheus-stack-grafana':
        d['data']['grafana.ini'] = d['data']['grafana.ini'].replace('[auth.anonymous]\nenabled = false', '[auth.anonymous]\nenabled = true')
    if d['kind'] == 'Deployment' and name in ('otel-loki', 'otel-tempo'):
        for v in d['spec']['template']['spec']['volumes']:
            if v['name'] == 'config':
                v['configMap']['name'] = 'otel-backends'
    return d

def test_existing_resources_have_one_service_owner_and_preserved_payload():
    fixture = json.loads((ROOT/'tests/fixtures/monitoring-split-contract.json').read_text())
    actual = {}
    for owner, (path, release) in OWNERS.items():
        for d in render(path, release):
            k = key(d)
            assert k not in actual, 'Duplicate owner: '+k
            actual[k] = (owner, d)
    for d in render('deploy/platform/grafana/public-entry', 'grafana-public-entry'):
        assert key(d) not in actual
        actual[key(d)] = ('grafana', d)
    for k, expected in fixture.items():
        if expected['owner'] in ('prometheus-stack', 'retired-shared-config'):
            continue
        owner, d = actual[k]
        assert owner == expected['owner'], k
        assert digest(normalized(d)) == expected.get('normalizedSha256', expected['sha256']), k

def test_grafana_native_sso_and_no_anonymous_access_are_declarative():
    v = yaml.safe_load((ROOT/'charts/grafana/values.yaml').read_text())['grafana']
    assert v['admin']['existingSecret'] == 'socrat-grafana-admin'
    assert v['grafana.ini']['auth.anonymous']['enabled'] is False
    assert v['env']['GF_AUTH_ANONYMOUS_ENABLED'] == 'false'
    assert v['env']['GF_AUTH_GENERIC_OAUTH_ENABLED'] == 'true'
    assert v['env']['GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN'] == 'true'
    assert v['env']['GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT'] == 'true'
    assert v['env']['GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP'] == 'false'
    assert 'GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET' not in v['env']
    assert v['envValueFrom']['GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET']['secretKeyRef'] == {'name': 'socrat-authentik-grafana', 'key': 'client-secret'}
    assert v['deploymentStrategy']['type'] == 'Recreate'
    assert v['nodeSelector'] == {'kubernetes.io/hostname': 'socrat-1'}
    dependency = yaml.safe_load((ROOT/'charts/grafana/charts/grafana/Chart.yaml').read_text())
    assert dependency['version'] == '14.0.0'

def test_each_backend_owns_its_config_without_changing_config_bytes():
    for name in ('loki', 'tempo'):
        docs = render('charts/'+name, name)
        config = next(d for d in docs if d['kind'] == 'ConfigMap')
        assert config['metadata']['name'] == 'otel-'+name+'-config'
        assert config['data'][name+'.yaml'] == (ROOT/f'deploy/monitoring/otel/{name}.yaml').read_text()
        dep = next(d for d in docs if d['kind'] == 'Deployment')
        volumes = {v['name']:v for v in dep['spec']['template']['spec']['volumes']}
        assert volumes['config']['configMap']['name'] == config['metadata']['name']
        assert volumes['tls']['secret']['secretName'] == 'otel-tls-backends'
        assert volumes['data']['hostPath']['path'] == '/var/lib/private/homelab-otel-'+name
        assert not any(d['kind'] in ('Certificate', 'Secret') for d in docs)

def test_prometheus_components_preserve_release_names_and_matching_labels():
    for name in COMPONENTS:
        a = yaml.safe_load((ROOT/f'deploy/argocd/apps/{name}.yaml').read_text())
        source = a['spec']['source']
        assert source['path'] == 'charts/'+name
        assert source['helm']['releaseName'] == 'kube-prometheus-stack'
        assert source['helm']['parameters'] == []
    v = yaml.safe_load((ROOT/'charts/prometheus/values.yaml').read_text())['kube-prometheus-stack']
    assert v['grafana'] == {'enabled': False}
    assert v['alertmanager']['enabled'] is False
    assert v['prometheus']['prometheusSpec']['ruleSelector']['matchLabels']['release'] == 'kube-prometheus-stack'
    assert v['prometheus']['prometheusSpec']['alertingEndpoints'][0]['name'] == 'kube-prometheus-stack-alertmanager'


def test_retired_aggregate_owners_and_charts_are_not_reintroduced():
    for name in ('kube-prometheus-stack', 'otel-backends', 'profiling'):
        assert not (ROOT/f'deploy/argocd/apps/{name}.yaml').exists()
    for name in ('otel-backends', 'profiling'):
        assert not (ROOT/f'charts/{name}').exists()
    assert not (ROOT/'deploy/platform/kube-prometheus-stack').exists()
    for name in ('grafana', 'loki', 'tempo', 'pyroscope', *COMPONENTS):
        app = yaml.safe_load((ROOT/f'deploy/argocd/apps/{name}.yaml').read_text())
        assert app['spec']['syncPolicy']['automated'].get('enabled') is not False
        assert app['spec']['syncPolicy']['automated']['prune'] is False
        assert app['spec']['syncPolicy']['automated']['selfHeal'] is True


def test_legacy_monitoring_installer_fails_before_roles_under_gitops():
    play = yaml.safe_load((ROOT/'ansible/playbooks/monitoring.yml').read_text())[1]
    guard = play['pre_tasks'][0]
    assert guard['ansible.builtin.include_role'] == {'name': 'monitoring_stack', 'tasks_from': 'gitops-guard.yml'}
    assert guard['tags'] == ['always']
    tasks = yaml.safe_load((ROOT/'ansible/roles/monitoring_stack/tasks/main.yml').read_text())
    assert tasks[0]['ansible.builtin.import_tasks'] == 'gitops-guard.yml'
    checks = yaml.safe_load((ROOT/'ansible/roles/monitoring_stack/tasks/gitops-guard.yml').read_text())
    assert len(checks) == 1
    assert 'ansible.builtin.fail' in checks[0]
    assert 'prometheus' in checks[0]['ansible.builtin.fail']['msg']
    assert 'alertmanager' in checks[0]['ansible.builtin.fail']['msg']
    assert checks[0]['tags'] == ['always']


def test_existing_rancher_postdelete_finalizers_are_declared_not_ignored():
    app = yaml.safe_load((ROOT/'deploy/argocd/apps/rancher.yaml').read_text())
    assert app['metadata']['finalizers'] == [
        'resources-finalizer.argocd.argoproj.io',
        'post-delete-finalizer.argocd.argoproj.io',
        'post-delete-finalizer.argocd.argoproj.io/cleanup',
    ]
