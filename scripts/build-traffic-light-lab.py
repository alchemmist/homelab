#!/usr/bin/env python3
"""Build an app-level Argo activity map in TMP, never edit the canonical TV."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
OUTPUT = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light-tmp-lab.json'
DS = {'type': 'prometheus', 'uid': 'prometheus'}


def fresh(metric, selector):
    return f'({metric}{{{selector}}} and (time() - timestamp({metric}{{{selector}}}) < 90))'


def queries(window='$__range'):
    job = 'job="socrat-argocd"'
    app = fresh('argocd_app_info', job)
    base = f'(0 * max by(name) ({app}))'
    gate = '(max(up{job="socrat-argocd"} == 1 and (time() - timestamp(up{job="socrat-argocd"}) < 90)) == 1)'

    def state(value, selector):
        return f'({value} * max by(name) ({fresh("argocd_app_info", job + "," + selector)}))'

    def sync(value, phase):
        counter = f'argocd_app_sync_total{{{job},phase=~"{phase}"}}'
        changed = f'sum by(name) (increase({counter}[10m]) and (time() - timestamp({counter}) < 90)) > 0'
        return f'({value} + 0 * ({changed}))'

    # Left-biased union after aggregation gives explicit state precedence.
    states = [state(6, 'health_status!~"Healthy|Progressing|Suspended|Degraded|Missing"'),
              state(6, 'sync_status!~"Synced|OutOfSync"'),
              state(5, 'health_status=~"Degraded|Missing"'), sync(4, 'Failed|Error'),
              state(3, 'health_status=~"Progressing|Suspended"'),
              state(2, 'sync_status="OutOfSync"'), sync(1, 'Succeeded'), base]
    activity = f'(({" or ".join(states)}) and on(name) {base}) and on() {gate}'

    # Select one cohort at range end, not a different top-k at every step.
    # Issues outrank sync volume. Only positive scores; quiet apps do not pad rows.
    issue_minutes = f'sum_over_time((({activity}) >= bool 2)[{window}:1m] @ end())'
    current_issue = f'last_over_time(({activity})[1m:1m] @ end()) >= 2'
    counters = f'sum by(name) (increase(argocd_app_sync_total{{{job}}}[{window}] @ end()))'
    zero = f'(0 * max by(name) (argocd_app_info{{{job}}} @ end()))'
    volume = f'({counters} or {zero})'
    history_score = f'(({issue_minutes}) or {zero})'
    severity = f'(({current_issue}) or {zero})'
    # Current issues first; then issue samples + sync volume. A transient unknown
    # must not crowd out all the apps that actually synced during the period.
    score = f'({volume} + on(name) (5 * {history_score}) + on(name) (1000000 * {severity}))'
    cohort = f'topk(8, {score} > 0)'
    return activity, cohort, f'({activity}) and on(name) ({cohort})'


def build():
    d = copy.deepcopy(json.loads(SOURCE.read_text()))
    d.pop('id', None)
    d.pop('version', None)
    d.update(uid='socrat-traffic-light-tmp-lab', title='Traffic Light · TMP Lab',
             description='Argo activity by application: syncs, drift and health transitions. Canonical TV unchanged.',
             tags=d.get('tags', []) + ['temporary', 'sandbox'])
    d['panels'] = [p for p in d['panels'] if p['id'] != 909]
    states = {
        '0': {'text': 'Quiet', 'color': '#252C36'},
        '1': {'text': 'Sync OK', 'color': '#56D6E7'},
        '2': {'text': 'Git drift', 'color': '#FFB357'},
        '3': {'text': 'Progressing / paused', 'color': '#B877D9'},
        '4': {'text': 'Sync failed', 'color': '#FF5263'},
        '5': {'text': 'Unhealthy', 'color': '#D02B4C'},
        '6': {'text': 'Unknown', 'color': '#808080'},
    }
    d['panels'].append({
        'id': 972, 'title': 'Argo CD · changes by app · top 8', 'type': 'state-timeline', 'datasource': DS,
        'gridPos': {'x': 12, 'y': 8, 'w': 6, 'h': 8},
        'description': 'One row per app, time left to right. Up to eight apps with activity/issues in the selected range; current issues rank first, then issue time and sync volume; cohort is fixed at range end. Dark = quiet, cyan = successful sync detected in the preceding 10m, amber = drift, violet = Progressing/Suspended, bright red = failed/error sync in preceding 10m, dark red = Degraded/Missing, grey = Unknown. Priority: unknown > unhealthy > sync failure > progressing/paused > drift > successful sync > quiet. Higher-priority states can hide a concurrent sync. Colors are observed/inferred states, not exact operation durations. Sync does NOT imply a Pod redeploy; Argo health is not a generic rollout/restart event feed. Missing/stale telemetry is a gap. No rows can mean no qualifying activity or unavailable telemetry; it is not an all-clear statement. Hover for app/time/state, click to investigate in Argo.',
        'interval': '1m', 'maxDataPoints': 720,
        'targets': [{'datasource': DS, 'expr': queries()[2], 'legendFormat': '{{name}}', 'refId': 'A',
                     'instant': False, 'range': True, 'format': 'time_series', 'interval': '1m'}],
        'fieldConfig': {'defaults': {'noValue': 'No telemetry', 'color': {'mode': 'palette-classic'},
                                    'mappings': [{'type': 'value', 'options': states}],
                                    'custom': {'axisPlacement': 'left', 'axisWidth': 125, 'fillOpacity': 100,
                                               'lineWidth': 0, 'spanNulls': False, 'insertNulls': 90000,
                                               'hideFrom': {'legend': False, 'tooltip': False, 'viz': False}},
                                    'links': [{'title': 'Open application in Argo CD',
                                               'url': 'https://argocd.socrat.alchemmist.xyz/applications/argocd/${__field.labels.name}',
                                               'targetBlank': True}]}, 'overrides': []},
        'options': {'rowHeight': 0.82, 'mergeValues': True, 'showValue': 'auto', 'alignValue': 'center',
                    'legend': {'showLegend': True, 'displayMode': 'list', 'placement': 'bottom'},
                    'tooltip': {'mode': 'single', 'sort': 'none'}},
    })
    d['panels'].sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
