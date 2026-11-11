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
    # Owner-edited canonical JSON owns all geometry and other panel settings.
    # This maintainer must not reconstruct a panel and overwrite manual edits.
    d = copy.deepcopy(json.loads(SOURCE.read_text()))
    panel = next(p for p in d['panels'] if p['id'] == 909)
    panel['options'].update(groupWidth=1, barWidth=1)
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
