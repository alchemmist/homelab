#!/usr/bin/env python3
"""Maintain the owner-approved Argo current-state strip in canonical panel909."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
OUTPUT = SOURCE
DS = {'type': 'prometheus', 'uid': 'prometheus'}
STATES = [('Ready', 4, '#26783D'), ('Progressing', 2, '#5794F2'),
          ('Git drift', 3, '#FFB357'), ('Unhealthy', 0, '#F2495C'), ('Unknown', 1, '#808080'), ('Suspended', 5, '#FFB357')]


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
        state(2, 'health_status="Progressing"'),
        state(5, 'health_status="Suspended"'),
        state(3, 'sync_status="OutOfSync"'),
        state(4, 'health_status="Healthy",sync_status="Synced"'),
        f'(1 * {apps})',
    ]) + ')'
    gate = ('(max(up{job="socrat-argocd"} == 1 and '
            '(time() - timestamp(up{job="socrat-argocd"}) < 90)) == 1)')
    # A partially stale scrape must not silently become a smaller healthy total.
    complete = f'(count({apps}) == count(max by(name) ({raw})))'
    # One query computes the partition once, rather than five heavy copies on a
    # dashboard refreshing every5s. Numeric codes are display keys, not severity scores.
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
    expr = f'label_replace(({queries()[2]}), "bar", "Argo", "", "")'
    order = ['bar\\state', '4', '2', '5', '3', '0', '1']
    d['panels'].append({
        'id': 909, 'title': '', 'transparent': True, 'type': 'barchart', 'datasource': DS,
        'gridPos': {'x': 12, 'y': 8, 'w': 6, 'h': 1},
        'description': 'Current Argo Applications, not history or Pod counts. Latest observed app_info only; raw samples were verified15s apart, dashboard refresh5s. No averaging/window/increase. root excluded. One segment per state, proportional to application count: Ready=Healthy+Synced; Progressing=not yet ready; Suspended=paused; drift=OutOfSync; Unhealthy=Degraded/Missing; Unknown=unknown/unrecognized state. Priority Unhealthy > Unknown > Progressing > Suspended > drift > Ready. Latest timestamp wins over lingering old label sets. Missing/down/partially stale telemetry gives no data, never a healthy green zero.90s freshness guard is a stale-data limit, not aggregation. Hover shows current counts. No proof of Pod rollout or full service health.',
        'interval': '15s', 'maxDataPoints': 1,
        'targets': [{'datasource': DS, 'expr': expr, 'legendFormat': '{{state}}', 'refId': 'A',
                     'instant': True, 'range': False, 'format': 'table'}],
        'transformations': [
            {'id': 'groupingToMatrix', 'options': {'columnField': 'state', 'rowField': 'bar', 'valueField': 'Value'}},
            {'id': 'organize', 'options': {'indexByName': {name: i for i, name in enumerate(order)}}},
        ],
        'fieldConfig': {'defaults': {'unit': 'short', 'decimals': 0, 'min': 0, 'max': 1, 'noValue': 'No telemetry',
                                    'color': {'mode': 'palette-classic'},
                                    'custom': {'lineWidth': 0, 'fillOpacity': 100, 'gradientMode': 'none',
                                               'axisPlacement': 'hidden', 'axisLabel': '',
                                               'axisBorderShow': False, 'axisGridShow': False,
                                               'scaleDistribution': {'type': 'linear'},
                                               'thresholdsStyle': {'mode': 'off'},
                                               'hideFrom': {'legend': False, 'tooltip': False, 'viz': False}}},
                        'overrides': [{'matcher': {'id': 'byName', 'options': str(code)}, 'properties': [
                            {'id': 'displayName', 'value': name},
                            {'id': 'color', 'value': {'mode': 'fixed', 'fixedColor': color}}]}
                                      for name, code, color in STATES]},
        'options': {'orientation': 'horizontal', 'stacking': 'percent', 'xField': 'bar\\state',
                    'groupWidth': 0.2, 'barWidth': 0.2, 'barRadius': 0, 'showValue': 'never',
                    'fullHighlight': True, 'xTickLabelRotation': 0, 'xTickLabelSpacing': 0,
                    'legend': {'showLegend': False, 'displayMode': 'list', 'placement': 'bottom', 'calcs': []},
                    'tooltip': {'mode': 'all', 'sort': 'desc', 'hideZeros': True}},
    })
    d['panels'].sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
