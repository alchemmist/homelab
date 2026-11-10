#!/usr/bin/env python3
"""Build the Argo-only native TMP proposal. Never edit the canonical dashboard."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
OUTPUT = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light-tmp-lab.json'
DS = {'type': 'prometheus', 'uid': 'prometheus'}


def target(expr, legend, ref, instant=True):
    return dict(datasource=DS, expr=expr, legendFormat=legend, refId=ref,
                instant=instant, range=not instant, format='time_series')


def fresh(metric, selector):
    return f'({metric}{{{selector}}} and (time() - timestamp({metric}{{{selector}}}) < 90))'


def build():
    d = copy.deepcopy(json.loads(SOURCE.read_text()))
    d.pop('id', None)
    d.pop('version', None)
    d.update(uid='socrat-traffic-light-tmp-lab', title='Traffic Light · TMP Lab',
             description='Argo-only visual sandbox: application state ring and sync activity. Canonical TV dashboard unchanged.',
             tags=d.get('tags', []) + ['temporary', 'sandbox'])
    d['panels'] = [p for p in d['panels'] if p['id'] != 909]
    gate = '(max(up{job="socrat-argocd"} == 1 and (time() - timestamp(up{job="socrat-argocd"}) < 90)) == 1)'
    all_apps = fresh('argocd_app_info', 'job="socrat-argocd"')
    # Disjoint categories: an app occupies exactly one slice, never two.
    groups = [
        ('Ready', 'health_status="Healthy",sync_status="Synced"', '#73BF69'),
        ('Git drift', 'health_status="Healthy",sync_status!="Synced"', '#FFB357'),
        ('Working', 'health_status=~"Progressing|Suspended"', '#5794F2'),
        ('Unhealthy', 'health_status=~"Degraded|Missing"', '#F2495C'),
        ('Unknown', 'health_status!~"Healthy|Progressing|Suspended|Degraded|Missing"', '#808080'),
    ]
    targets, overrides = [], []
    for i, (name, selector, color) in enumerate(groups):
        selected = fresh('argocd_app_info', f'job="socrat-argocd",{selector}')
        expr = f'((count({selected}) or (0 * count({all_apps}))) and on() {gate})'
        targets.append(target(expr, name, chr(65 + i)))
        overrides.append({'matcher': {'id': 'byName', 'options': name}, 'properties': [
            {'id': 'color', 'value': {'mode': 'fixed', 'fixedColor': color}}]})
    links = [{'title': 'Open Argo CD', 'url': 'https://argocd.socrat.alchemmist.xyz/applications', 'targetBlank': True}]
    d['panels'].append({
        'id': 970, 'title': 'Argo CD · application states', 'type': 'piechart', 'datasource': DS,
        'gridPos': {'x': 12, 'y': 8, 'w': 6, 'h': 4},
        'description': 'Current app state distribution. One app = one slice contribution. Ready: Healthy+Synced; drift: Healthy but not Synced; Working includes Progressing and Suspended; Unhealthy: Degraded/Missing; Unknown: other health states. Nonhealthy health takes priority over sync drift. Missing/stale telemetry is not a healthy ring. Hover for counts.',
        'targets': targets,
        'fieldConfig': {'defaults': {'unit': 'short', 'decimals': 0, 'min': 0,
                                    'color': {'mode': 'palette-classic'}, 'noValue': 'No telemetry',
                                    'mappings': [], 'links': links}, 'overrides': overrides},
        'options': {'pieType': 'donut', 'displayLabels': [], 'sort': 'none',
                    'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                    'legend': {'showLegend': True, 'displayMode': 'list', 'placement': 'bottom', 'values': []},
                    'tooltip': {'mode': 'single', 'sort': 'none', 'hideZeros': True}},
    })
    counter = 'argocd_app_sync_total{job="socrat-argocd"}'
    activity = f'(sum by(phase) (increase({counter}[15m]) and (time() - timestamp({counter}) < 90))) and on() {gate}'
    d['panels'].append({
        'id': 971, 'title': 'Argo CD · sync activity · 15m buckets', 'type': 'timeseries', 'datasource': DS,
        'gridPos': {'x': 12, 'y': 12, 'w': 6, 'h': 4},
        'description': 'Estimated completed sync operations per 15-minute window over the dashboard range. Green: Succeeded; orange: Failed; red: Error. Query step is 15m, matching the increase window. Counter resets handled by increase; fractional counts are estimates, not exact event logs. Fresh quiet periods are zero; stale/missing telemetry stays a gap. Automatic reconciliation without a sync does not count.',
        'interval': '15m', 'maxDataPoints': 48,
        'targets': [dict(target(activity, '{{phase}}', 'A', False), interval='15m')],
        'fieldConfig': {'defaults': {'unit': 'short', 'decimals': 0, 'min': 0, 'noValue': 'No telemetry',
                                    'color': {'mode': 'palette-classic'}, 'links': links,
                                    'custom': {'drawStyle': 'bars', 'barAlignment': 0, 'barWidthFactor': 0.8,
                                               'fillOpacity': 90, 'lineWidth': 0, 'gradientMode': 'opacity',
                                               'stacking': {'mode': 'normal', 'group': 'sync'},
                                               'axisPlacement': 'left', 'axisLabel': '', 'axisBorderShow': False,
                                               'axisGridShow': True, 'spanNulls': False,
                                               'showPoints': 'never', 'scaleDistribution': {'type': 'linear'},
                                               'thresholdsStyle': {'mode': 'off'},
                                               'hideFrom': {'legend': False, 'tooltip': False, 'viz': False}}},
                        'overrides': [{'matcher': {'id': 'byName', 'options': name}, 'properties': [
                            {'id': 'color', 'value': {'mode': 'fixed', 'fixedColor': color}}]}
                                      for name, color in [('Succeeded', '#73BF69'), ('Failed', '#FFB357'), ('Error', '#F2495C')]]},
        'options': {'legend': {'showLegend': True, 'displayMode': 'list', 'placement': 'bottom', 'calcs': []},
                    'tooltip': {'mode': 'all', 'sort': 'desc', 'hideZeros': True}},
    })
    d['panels'].sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
