#!/usr/bin/env python3
"""Build only the TMP Argo per-application sync line chart; never edit TV."""
import colorsys
import copy
import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
OUTPUT = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light-tmp-lab.json'
DS = {'type': 'prometheus', 'uid': 'prometheus'}


def fresh(metric, selector):
    return f'({metric}{{{selector}}} and (time() - timestamp({metric}{{{selector}}}) < 90))'


def query():
    selector = 'job="socrat-argocd",name!="root"'
    counter = f'argocd_app_sync_total{{{selector},phase="Succeeded"}}'
    apps = f'max by(name) ({fresh("argocd_app_info", selector)})'
    increments = f'sum by(name) (increase({counter}[15m]) and (time() - timestamp({counter}) < 90))'
    gate = '(max(up{job="socrat-argocd"} == 1 and (time() - timestamp(up{job="socrat-argocd"}) < 90)) == 1)'
    # Fresh apps without an initialized success counter are represented at zero.
    # Retired counter label sets cannot create ghost application lines.
    return f'(({increments} or (0 * {apps})) and on(name) {apps}) and on() {gate}'


def application_names():
    names = []
    paths = sorted((ROOT / 'deploy/argocd/apps').glob('*.yaml')) + [ROOT / 'deploy/argocd/root.yaml']
    for path in paths:
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get('kind') == 'Application':
                names.append(doc['metadata']['name'])
    if len(names) != len(set(names)):
        raise ValueError('Duplicate Argo application names')
    return sorted(name for name in names if name != 'root')


def application_color(name):
    # Stable per name: adding/removing or reordering another app changes no color.
    digest = hashlib.sha256(name.encode()).digest()
    hue = int.from_bytes(digest[:4], 'big') / 2**32
    saturation = 0.64 + digest[4] / 255 * 0.20
    red, green, blue = colorsys.hls_to_rgb(hue, 0.64, saturation)
    return '#{:02X}{:02X}{:02X}'.format(round(red * 255), round(green * 255), round(blue * 255))


def build():
    d = copy.deepcopy(json.loads(SOURCE.read_text()))
    d.pop('id', None)
    d.pop('version', None)
    d.update(uid='socrat-traffic-light-tmp-lab', title='Traffic Light · TMP Lab',
             description='Argo successful syncs by application, rolling 15m, root excluded. Canonical TV unchanged.',
             tags=d.get('tags', []) + ['temporary', 'sandbox'])
    d['panels'] = [p for p in d['panels'] if p['id'] != 909]
    d['panels'].append({
        'id': 974, 'title': 'Argo CD · syncs by app · 15m', 'type': 'timeseries', 'datasource': DS,
        'gridPos': {'x': 12, 'y': 8, 'w': 6, 'h': 8},
        'description': 'Each color is an application; root is excluded. Estimated successful Argo syncs in the preceding 15 minutes, sampled every minute across the selected dashboard range. A sync may apply configuration without redeploying Pods. This is a rolling count, not a lifetime counter, exact event log or failure chart. Lines overlap when values coincide; hover selects an application. Fresh applications with no initialized success counter show zero. Retired apps excluded using fresh app_info; missing/stale app or scrape telemetry stays a gap. Known app colors are pinned by name; regenerate overrides for new Git apps. No legend or top-k.',
        'interval': '1m', 'maxDataPoints': 720,
        'targets': [{'datasource': DS, 'expr': query(), 'legendFormat': '{{name}}', 'refId': 'A',
                     'instant': False, 'range': True, 'format': 'time_series', 'interval': '1m'}],
        'fieldConfig': {'defaults': {'unit': 'short', 'decimals': 0, 'min': 0, 'noValue': 'No telemetry',
                                    'color': {'mode': 'palette-classic'},
                                    'links': [{'title': 'Open application in Argo CD',
                                               'url': 'https://argocd.socrat.alchemmist.xyz/applications/argocd/${__field.labels.name}',
                                               'targetBlank': True}],
                                    'custom': {'drawStyle': 'line', 'lineInterpolation': 'linear', 'lineWidth': 2,
                                               'fillOpacity': 0, 'gradientMode': 'none', 'showPoints': 'never',
                                               'spanNulls': False, 'insertNulls': 90000,
                                               'stacking': {'mode': 'none', 'group': 'A'},
                                               'axisPlacement': 'left', 'axisLabel': 'Syncs / 15m',
                                               'axisBorderShow': False, 'axisGridShow': True, 'axisSoftMax': 2,
                                               'scaleDistribution': {'type': 'linear'},
                                               'thresholdsStyle': {'mode': 'off'},
                                               'hideFrom': {'legend': False, 'tooltip': False, 'viz': False}}},
                        'overrides': [{'matcher': {'id': 'byName', 'options': name}, 'properties': [
                            {'id': 'color', 'value': {'mode': 'fixed', 'fixedColor': application_color(name)}}]}
                                      for name in application_names()]},
        'options': {'legend': {'showLegend': False, 'displayMode': 'list', 'placement': 'bottom', 'calcs': []},
                    'tooltip': {'mode': 'single', 'sort': 'none'}},
    })
    d['panels'].sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
