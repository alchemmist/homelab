"""Short time pickers must not shrink increase below the scrape interval."""
import json
from pathlib import Path


def test_requests_window_is_independent_of_time_picker():
    d = json.loads((Path(__file__).resolve().parents[1] / 'charts/monitoring-k3s/dashboards/llm-keys.json').read_text())
    p = next(p for p in d['panels'] if p['id'] == 1)
    expr = p['targets'][0]['expr']
    assert 'increase(' in expr and '[1m]' in expr
    assert '$__interval' not in expr
    assert 'or vector(0)' not in expr
    assert p['fieldConfig']['defaults']['custom']['spanNulls'] is False
    assert p['fieldConfig']['defaults']['custom']['axisLabel'] == 'requests / rolling minute'
    assert 'must not be summed' in p['description']
    table = next(p for p in d['panels'] if p['id'] == 4)
    assert all('[30d]' in t['expr'] for t in table['targets'])


def test_temporary_acceptance_keys_are_not_user_activity():
    d = json.loads((Path(__file__).resolve().parents[1] / 'charts/monitoring-k3s/dashboards/llm-keys.json').read_text())
    targets = [t for p in d['panels'] for t in p.get('targets', [])]
    assert len(targets) == 4
    assert all('api_key_alias!~"venice-acceptance-.*"' in t['expr'] for t in targets)


def test_models_are_separate_and_public_content_is_aggregate():
    d = json.loads((Path(__file__).resolve().parents[1] / 'charts/monitoring-k3s/dashboards/llm-keys.json').read_text())
    assert len(d['panels']) == 3
    assert d['annotations'] == {'list': []}
    assert d['time']['from'] == 'now-1h'
    for panel, model in zip(d['panels'][:2], ['qwen3.8-27b', 'venice-agentic-deepseek-v4.1-flash-uncensored']):
        expr = panel['targets'][0]['expr']
        assert 'model="' + model + '"' in expr
        assert 'sum by (api_key_alias)' in expr
        assert '[1m]' in expr and '$__interval' not in expr
    assert d['panels'][2]['gridPos']['y'] == 16
    assert all(p['gridPos']['h'] == 8 for p in d['panels'][:2])


def test_chart_titles_use_litellm_route_names():
    d = json.loads((Path(__file__).resolve().parents[1] / 'charts/monitoring-k3s/dashboards/llm-keys.json').read_text())
    assert [p['title'] for p in d['panels'][:2]] == [
        'Requests by API key — qwen3.8-27b',
        'Requests by API key — venice-deepseek',
    ]
