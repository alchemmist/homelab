"""Public exposure contract: aggregate labels only and honest activity semantics."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_llm_dashboard_is_one_safe_panel():
    d = json.loads((ROOT / 'charts/monitoring-k3s/dashboards/llm-activity-public.json').read_text())
    assert d['uid'] == 'socrat-llm-activity-public'
    assert len(d['panels']) == 1
    assert d['templating'] == {'list': []}
    assert d['annotations'] == {'list': []}
    assert d['links'] == []
    assert d['refresh'] == '10s'
    p = d['panels'][0]
    assert p['gridPos']['w'] == 24
    assert p['targets'][0]['expr'] == 'sum by (api_key_alias) (rate(litellm_requests_metric_total{job="litellm",api_key_alias!="",api_key_alias!="None"}[$__rate_interval])) * 60'
    assert p['targets'][0]['legendFormat'] == '{{api_key_alias}}'
    assert p['fieldConfig']['defaults']['custom']['spanNulls'] is False
    assert 'zero does not guarantee' in p['description']
    assert 'completed' in p['title']


def test_public_sharing_does_not_enable_org_anonymous():
    source = (ROOT / 'scripts/grafana-llm-public.py').read_text()
    assert "settings.get('auth.anonymous'" in source
    assert "'annotationsEnabled':False" in source
    assert "'timeSelectionEnabled':True" in source
    assert "need(a.approve_plan_hash==digest" in source
    assert "live['panels']==expected['panels']" in source
