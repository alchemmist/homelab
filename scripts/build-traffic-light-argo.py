#!/usr/bin/env python3
"""Maintain the owner-approved Argo landscape in canonical panel909."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
OUTPUT = SOURCE
DS = {'type': 'prometheus', 'uid': 'prometheus'}
STATES = [('Ready', 4, '#173B2B'), ('Progressing / paused', 2, '#5794F2'),
          ('Git drift', 3, '#FFB357'), ('Unhealthy', 0, '#F2495C'), ('Unknown', 1, '#808080')]


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
        state(0, 'health_status=~"Degraded|Missing"'),
        state(1, 'health_status!~"Healthy|Progressing|Suspended|Degraded|Missing"'),
        state(1, 'sync_status!~"Synced|OutOfSync"'),
        state(2, 'health_status=~"Progressing|Suspended"'),
        state(3, 'sync_status="OutOfSync"'),
        state(4, 'health_status="Healthy",sync_status="Synced"'),
        f'(1 * {apps})',
    ]) + ')'
    gate = ('(max(up{job="socrat-argocd"} == 1 and '
            '(time() - timestamp(up{job="socrat-argocd"}) < 90)) == 1)')
    # A partially stale scrape must not silently become a smaller healthy total.
    complete = f'(count({apps}) == count(max by(name) ({raw})))'
    # One query computes the partition once, rather than five heavy copies on a
    # dashboard refreshing every5s. Numeric state labels put deviations below Ready (last) in range results.
    counts = f'count_values("state", {state_expr})'
    zeros = [f'label_replace((0 * count({apps})), "state", "{code}", "", "")'
             for _, code, _ in STATES]
    full_query = f'(({counts} or {" or ".join(zeros)}) and on() {gate}) and on() {complete}'
    result = []
    for name, code, color in STATES:
        # Used for isolated per-category PromQL assertions, not dashboard targets.
        expr = f'sum(({full_query}) and on(state) label_replace(vector(1), "state", "{code}", "", ""))'
        result.append((name, expr, color))
    return state_expr, result, full_query


def build():
    d = copy.deepcopy(json.loads(SOURCE.read_text()))
    d['panels'] = [p for p in d['panels'] if p['id'] != 909]
    d['panels'].append({
        'id': 909, 'title': '', 'type': 'timeseries', 'datasource': DS,
        'gridPos': {'x': 12, 'y': 8, 'w': 6, 'h': 6},
        'description': 'Stacked application counts by observed Argo state over the selected range, sampled every15s. root excluded. Dark green = Healthy+Synced; blue = Progressing/Suspended; amber = drift; red = Degraded/Missing; grey = Unknown/unrecognized states. Each app contributes once. Priority: Unhealthy > Unknown > Progressing/paused > drift > Ready. Latest timestamp wins over older state label sets. Fresh zeros require app telemetry; missing/down/partially stale scrapes remain gaps. All applications are counted, not top-k. Progressing is not proof of a Pod rollout; Suspended is paused. A changing total may reflect added/removed apps or unavailable inventory after lookback expiry. Hover shows counts, not individual app names or root cause. No sync counter/event smoothing. Symlog base2, linear threshold1: zero retained, deviations stacked below Ready. Layer thickness is nonlinear; use axis/tooltip for actual app counts.',
        'interval': '15s', 'maxDataPoints': 10000,
        'targets': [{'datasource': DS, 'expr': queries()[2], 'legendFormat': '{{state}}', 'refId': 'A',
                     'instant': False, 'range': True, 'format': 'time_series', 'interval': '15s'}],
        'fieldConfig': {'defaults': {'unit': 'short', 'decimals': 0, 'min': 0, 'noValue': 'No telemetry',
                                    'color': {'mode': 'palette-classic'},
                                    'custom': {'drawStyle': 'line', 'lineInterpolation': 'stepAfter', 'lineWidth': 0,
                                               'fillOpacity': 85, 'gradientMode': 'none', 'showPoints': 'never',
                                               'spanNulls': False, 'insertNulls': 45000,
                                               'stacking': {'mode': 'normal', 'group': 'argo-state'},
                                               'axisPlacement': 'left', 'axisLabel': '',
                                               'axisBorderShow': False, 'axisGridShow': True,
                                               'scaleDistribution': {'type': 'symlog', 'log': 2, 'linearThreshold': 1},
                                               'thresholdsStyle': {'mode': 'off'},
                                               'hideFrom': {'legend': False, 'tooltip': False, 'viz': False}}},
                        'overrides': [{'matcher': {'id': 'byName', 'options': str(code)}, 'properties': [
                            {'id': 'displayName', 'value': name},
                            {'id': 'color', 'value': {'mode': 'fixed', 'fixedColor': color}}]}
                                      for name, code, color in STATES]},
        'options': {'legend': {'showLegend': True, 'displayMode': 'list', 'placement': 'bottom', 'calcs': []},
                    'tooltip': {'mode': 'all', 'sort': 'desc', 'hideZeros': True}},
    })
    d['panels'].sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
