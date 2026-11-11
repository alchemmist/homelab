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


def queries(include_root=False):
    selector = 'job="socrat-argocd"' + ('' if include_root else ',name!="root"')
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


def application_query():
    """One positive status code per fresh Application; NOT a percentage/count."""
    raw = 'argocd_app_info{job="socrat-argocd"}'
    fresh = f'({raw} and (time() - timestamp({raw}) < 90))'
    gate = ('(max(up{job="socrat-argocd"} == 1 and '
            '(time() - timestamp(up{job="socrat-argocd"}) < 90)) == 1)')
    complete = f'(count(max by(name) ({fresh})) == count(max by(name) ({raw})))'
    return f'(({queries(include_root=True)[0]} + 1) and on() {gate}) and on() {complete}'


def build():
    d = copy.deepcopy(json.loads(SOURCE.read_text()))
    panel = next(p for p in d['panels'] if p['id'] == 909)
    grid = dict(panel['gridPos'], h=2)
    panel.clear()
    panel.update({
        'id': 909, 'title': '', 'transparent': True, 'type': 'bargauge',
        'datasource': DS, 'gridPos': grid,
        'description': 'Current Argo Applications, not Pods/history. One equal full block per Application, alphabetically ordered by name; color encodes latest status. Numeric codes1..6 are categorical, not utilization or readiness percentage; max1 intentionally saturates every present block to the same size. Ready=Healthy+Synced, Progressing, Suspended, Git drift=OutOfSync, Unhealthy=Degraded/Missing, Unknown. Latest timestamp wins, priority Unhealthy > Unknown > Progressing > Suspended > drift > Ready. root included so every Argo Application has a block. Hover shows Application name through a native single data link; click opens that Application in Argo CD. Freshness90s and up/inventory completeness guards: unavailable/down/partially stale telemetry produces no data, never green fabricated blocks. Raw sampling15s; dashboard refresh5s. Native Bar gauge solid value-mapped colors, not LCD subdivisions: each whole block corresponds to one Application.',
        'interval': '15s', 'maxDataPoints': 1,
        'targets': [{'datasource': DS, 'expr': application_query(), 'legendFormat': '{{name}}',
                     'refId': 'A', 'instant': True, 'range': False, 'format': 'time_series'}],
        'transformations': [
            {'id': 'seriesToRows', 'options': {}},
            {'id': 'sortBy', 'options': {'sort': [{'field': 'Metric', 'desc': False}]}},
            {'id': 'rowsToFields', 'options': {'mappings': [
                {'fieldName': 'Metric', 'handlerKey': 'field.name'},
                {'fieldName': 'Value', 'handlerKey': 'field.value'}]}},
        ],
        'fieldConfig': {'defaults': {
            'min': 0, 'max': 1, 'decimals': 0, 'unit': 'short', 'noValue': 'No telemetry',
            'color': {'mode': 'fixed', 'fixedColor': '#808080'},
            'links': [{'title': '${__field.name}',
                       'url': 'https://argocd.socrat.alchemmist.xyz/applications/argocd/${__field.name}',
                       'targetBlank': True}],
            'mappings': [{'type': 'value', 'options': {str(code + 1): {'text': name, 'color': color}
                                                    for name, code, color in STATES}}],
            'thresholds': {'mode': 'absolute', 'steps': [
                {'value': None, 'color': '#808080'}] + [
                {'value': code + 1, 'color': color} for _, code, color in sorted(STATES, key=lambda s: s[1])]},
        }, 'overrides': []},
        'options': {'orientation': 'vertical', 'displayMode': 'gradient',
                    'valueMode': 'hidden', 'namePlacement': 'hidden', 'textMode': 'none',
                    'showUnfilled': False, 'sizing': 'manual', 'minVizWidth': 0, 'minVizHeight': 0,
                    'maxVizHeight': 300,
                    'reduceOptions': {'values': False, 'calcs': ['lastNotNull'], 'fields': ''},
                    'legend': {'showLegend': False, 'displayMode': 'list', 'placement': 'bottom', 'calcs': []}},
    })
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
