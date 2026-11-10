#!/usr/bin/env python3
"""Build only the TMP Argo state landscape, never edit the canonical TV."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
OUTPUT = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light-tmp-lab.json'
DS = {'type': 'prometheus', 'uid': 'prometheus'}
STATES = [('Ready', 0, '#173B2B'), ('Progressing / paused', 2, '#5794F2'),
          ('Git drift', 1, '#FFB357'), ('Unhealthy', 4, '#F2495C'), ('Unknown', 3, '#808080')]


def queries():
    selector = 'job="socrat-argocd",name!="root"'
    raw = f'argocd_app_info{{{selector}}}'
    newest = f'max by(name) (timestamp({raw}))'

    def latest(extra=''):
        metric = f'argocd_app_info{{{selector}{"," + extra if extra else ""}}}'
        # Discard old label sets lingering after a state change in OTLP storage.
        return f'({metric} and (time() - timestamp({metric}) < 90) and (timestamp({metric}) == on(name) group_left {newest}))'

    apps = f'max by(name) ({latest()})'
    def state(code, extra):
        return f'({code} * max by(name) ({latest(extra)}))'

    # Union is left-biased after aggregation by name: exactly one code per app.
    state_expr = '(' + ' or '.join([
        state(4, 'health_status=~"Degraded|Missing"'),
        state(3, 'health_status!~"Healthy|Progressing|Suspended|Degraded|Missing"'),
        state(3, 'sync_status!~"Synced|OutOfSync"'),
        state(2, 'health_status=~"Progressing|Suspended"'),
        state(1, 'sync_status="OutOfSync"'),
        state(0, 'health_status="Healthy",sync_status="Synced"'),
        f'(3 * {apps})',
    ]) + ')'
    gate = ('(max(up{job="socrat-argocd"} == 1 and '
            '(time() - timestamp(up{job="socrat-argocd"}) < 90)) == 1)')
    # A partially stale scrape must not silently become a smaller healthy total.
    complete = f'(count({apps}) == count(max by(name) ({raw})))'
    result = []
    for name, code, color in STATES:
        expr = f'((count({state_expr} == {code}) or (0 * count({state_expr}))) and on() {gate}) and on() {complete}'
        result.append((name, expr, color))
    return state_expr, result


def build():
    d = copy.deepcopy(json.loads(SOURCE.read_text()))
    d.pop('id', None)
    d.pop('version', None)
    d.update(uid='socrat-traffic-light-tmp-lab', title='Traffic Light · TMP Lab',
             description='Argo application state landscape over the dashboard range, root excluded. Canonical TV unchanged.',
             tags=d.get('tags', []) + ['temporary', 'sandbox'])
    d['panels'] = [p for p in d['panels'] if p['id'] != 909]
    groups = queries()[1]
    d['panels'].append({
        'id': 975, 'title': '', 'type': 'timeseries', 'datasource': DS,
        'gridPos': {'x': 12, 'y': 8, 'w': 6, 'h': 7},
        'description': 'Stacked application counts by observed Argo state over the selected range, sampled every15s. root excluded. Dark green = Healthy+Synced; blue = Progressing/Suspended; amber = drift; red = Degraded/Missing; grey = Unknown/unrecognized states. Each app contributes once. Priority: Unhealthy > Unknown > Progressing/paused > drift > Ready. Latest timestamp wins over older state label sets. Fresh zeros require app telemetry; missing/down/partially stale scrapes remain gaps. All applications are counted, not top-k. Progressing is not proof of a Pod rollout; Suspended is paused. A changing total may reflect added/removed apps or unavailable inventory after lookback expiry. Hover shows counts, not individual app names or root cause. No sync counter/event smoothing.',
        'interval': '15s', 'maxDataPoints': 10000,
        'targets': [{'datasource': DS, 'expr': expr, 'legendFormat': name, 'refId': chr(65 + i),
                     'instant': False, 'range': True, 'format': 'time_series', 'interval': '15s'}
                    for i, (name, expr, _) in enumerate(groups)],
        'fieldConfig': {'defaults': {'unit': 'short', 'decimals': 0, 'min': 0, 'noValue': 'No telemetry',
                                    'color': {'mode': 'palette-classic'},
                                    'custom': {'drawStyle': 'line', 'lineInterpolation': 'stepAfter', 'lineWidth': 1,
                                               'fillOpacity': 85, 'gradientMode': 'none', 'showPoints': 'never',
                                               'spanNulls': False, 'insertNulls': 45000,
                                               'stacking': {'mode': 'normal', 'group': 'argo-state'},
                                               'axisPlacement': 'left', 'axisLabel': '',
                                               'axisBorderShow': False, 'axisGridShow': True,
                                               'scaleDistribution': {'type': 'linear'},
                                               'thresholdsStyle': {'mode': 'off'},
                                               'hideFrom': {'legend': False, 'tooltip': False, 'viz': False}}},
                        'overrides': [{'matcher': {'id': 'byName', 'options': name}, 'properties': [
                            {'id': 'color', 'value': {'mode': 'fixed', 'fixedColor': color}}]}
                                      for name, _, color in groups]},
        'options': {'legend': {'showLegend': True, 'displayMode': 'list', 'placement': 'bottom', 'calcs': []},
                    'tooltip': {'mode': 'all', 'sort': 'desc', 'hideZeros': True}},
    })
    d['panels'].sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
