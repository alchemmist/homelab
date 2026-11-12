"""Contracts for a Grafana-only network overview; no synthetic mesh health."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'charts/monitoring-k3s/dashboards/network.json'


def dashboard():
    return json.loads(PATH.read_text())


def test_native_panels_and_existing_datasource_only():
    d = dashboard()
    assert d['uid'] == 'socrat-network'
    assert d['refresh'] == '30s'
    assert len({p['id'] for p in d['panels']}) == len(d['panels'])
    for p in d['panels']:
        assert p['type'] in {'text', 'stat', 'table', 'timeseries', 'nodeGraph'}
        for t in p.get('targets', []):
            assert t['datasource'] == {'type': 'prometheus', 'uid': 'prometheus'}
            assert 'vector(' not in t['expr']  # No fabricated discovery or healthy fallback.


def test_graphs_have_native_edge_schema_and_instant_tables():
    graphs = [p for p in dashboard()['panels'] if p['type'] == 'nodeGraph']
    assert len(graphs) == 2
    for p in graphs:
        t = p['targets'][0]
        assert t['refId'] == 'edges'
        assert t['instant'] and not t['range'] and t['format'] == 'table'
        names = p['transformations'][0]['options']['include']['names']
        assert {'id', 'source', 'target', 'Value'} <= set(names)
        assert p['transformations'][1]['options']['renameByName']['Value'] == 'mainstat'
        assert 'timestamp(' in t['expr'] and '< 120' in t['expr']


def test_probe_color_requires_real_fresh_success_or_failure():
    p = next(p for p in dashboard()['panels'] if p['id'] == 4)
    q = p['targets'][0]['expr']
    assert 'probe_success' in q and 'job="service-probes"' in q
    assert '== 1' in q and '== 0' in q
    assert '#73BF69' in q and '#F2495C' in q
    assert 'detail__observer' in q and 'detail__endpoint' in q
    assert '${probe_group:regex}' in q


def test_placement_is_not_colored_as_connectivity():
    p = next(p for p in dashboard()['panels'] if p['id'] == 5)
    q = p['targets'][0]['expr']
    assert 'kube_pod_info' in q and 'kube_pod_status_phase' in q
    assert 'phase="Running"' in q
    assert 'color' not in q and 'probe_success' not in q
    assert '${namespace:regex}' in q
    assert 'not imply network health' in p['description']


def test_scope_and_unknown_state_are_explicit():
    text = next(p for p in dashboard()['panels'] if p['type'] == 'text')['options']['content']
    assert 'не обнаруживает' in text
    assert 'No data' in text and 'не восстановление' in text
    assert 'одного cluster-prober' in text
    assert 'Ready ≠' in text


def test_dashboard_uses_existing_provisioning_owner():
    template = (ROOT / 'charts/monitoring-k3s/templates/socrat-dashboard.yaml').read_text()
    assert '"network"' in template
    assert 'grafana_dashboard: "1"' in template
