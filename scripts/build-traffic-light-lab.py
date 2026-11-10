#!/usr/bin/env python3
"""Build an app-level Argo activity map in TMP, never edit the canonical TV."""
import copy
import json
import math

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
OUTPUT = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light-tmp-lab.json'
DS = {'type': 'prometheus', 'uid': 'prometheus'}


def fresh(metric, selector):
    return f'({metric}{{{selector}}} and (time() - timestamp({metric}{{{selector}}}) < 90))'


def query():
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

    return activity


def application_names():
    names = []
    paths = sorted((ROOT / 'deploy/argocd/apps').glob('*.yaml')) + [ROOT / 'deploy/argocd/root.yaml']
    for path in paths:
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get('kind') == 'Application':
                names.append(doc['metadata']['name'])
    if len(names) != len(set(names)):
        raise ValueError('Duplicate Argo application names')
    return sorted(names)


ALIASES = {
    'alertmanager': 'Alerts', 'argo-cd': 'Argo', 'cert-manager': 'Certs',
    'cnpg-operator': 'CNPG', 'format-quorum': 'Quorum', 'grafana-mcp': 'Gf MCP',
    'img-proxy': 'Img proxy', 'kube-state-metrics': 'KSM', 'litellm-infra': 'LLM infra',
    'monitoring-k3s': 'Mon K3s', 'monitoring-llm': 'Mon LLM', 'node-exporter': 'Node exp',
    'nvidia-device-plugin': 'NVIDIA', 'open-terminal': 'Terminal', 'open-webui': 'WebUI',
    'private-gateway': 'Priv GW', 'prometheus': 'Prom', 'prometheus-operator': 'Prom Op',
    'pyroscope': 'Pyroscope', 'socrat-bot': 'Bot', 'socrat-home': 'Home',
    'spi-triage': 'SPI', 'traefik-edge': 'Edge', 'uptime-kuma': 'Kuma',
    'vpn-transit': 'VPN MSK', 'wiki-runtime': 'Wiki',
}


def tile(name, label, left, top, width=57, height=40, color=None):
    return {
        'name': name, 'type': 'rectangle',
        'placement': {'left': left, 'top': top, 'width': width, 'height': height, 'rotation': 0},
        'constraint': {'horizontal': 'scale', 'vertical': 'scale'},
        'background': {'color': {'fixed': color or '#555555', **({} if color else {'field': name})}},
        'border': {'width': 1, 'radius': 5, 'color': {'fixed': '#424B58'}},
        'config': {'align': 'center', 'valign': 'middle', 'size': 10 if color else 11,
                   'color': {'fixed': '#FFFFFF'},
                   'text': {'mode': 'fixed', 'fixed': label, **({} if color else {'field': name})}},
        'links': [] if color else [{'title': name + ' · Open in Argo CD',
                                   'url': 'https://argocd.socrat.alchemmist.xyz/applications/argocd/' + name,
                                   'targetBlank': True}],
    }


def build():
    d = copy.deepcopy(json.loads(SOURCE.read_text()))
    d.pop('id', None)
    d.pop('version', None)
    d.update(uid='socrat-traffic-light-tmp-lab', title='Traffic Light · TMP Lab',
             description='All Git-managed Argo applications in one native Canvas mosaic. Canonical TV unchanged.',
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
    names = application_names()
    columns = 7
    rows = math.ceil(len(names) / columns)
    labels = [ALIASES.get(name, name) for name in names]
    if len(set(labels)) != len(labels):
        raise ValueError('Ambiguous mosaic aliases')
    elements = [tile(name, label, (i % columns) * 60, 26 + (i // columns) * 44)
                for i, (name, label) in enumerate(zip(names, labels))]
    for i, (code, label) in enumerate([('0', 'Quiet'), ('1', 'Sync'), ('2', 'Drift'),
                                       ('3', 'Work'), ('4', 'Fail'), ('5', 'Down'), ('6', '?')]):
        elements.append(tile('Legend ' + code, label, i * 60, 0, height=18, color=states[code]['color']))
    d['panels'].append({
        'id': 973, 'title': 'Argo CD · all apps', 'type': 'canvas', 'datasource': DS,
        'gridPos': {'x': 12, 'y': 8, 'w': 6, 'h': 8},
        'description': 'One fixed cell per Git-managed Argo application, alphabetical; no top-k or scrolling. Short names on cells, full names and mapped states in native hover. Quiet is subdued; cyan = successful sync in preceding 10m, amber = drift, violet = Progressing/Suspended, bright red = failed sync in preceding 10m, dark red = Degraded/Missing, grey = Unknown/missing/stale data. Priority: unknown > unhealthy > failed sync > progressing/paused > drift > recent success > quiet. Current state only, not history. Sync is not proof of a Pod redeploy. Click a cell to open its app. Inventory comes from Git; regenerate when apps are added/removed.',
        'targets': [{'datasource': DS, 'expr': query(), 'legendFormat': '{{name}}', 'refId': 'A',
                     'instant': True, 'range': False, 'format': 'time_series'}],
        'fieldConfig': {'defaults': {'noValue': 'No telemetry', 'color': {'mode': 'thresholds'},
                                    'mappings': [{'type': 'value', 'options': states},
                                                 {'type': 'special', 'options': {'match': 'null+nan',
                                                  'result': {'text': 'No telemetry', 'color': '#555555'}}}],
                                    'thresholds': {'mode': 'absolute', 'steps': [
                                        {'value': None if k == '0' else int(k), 'color': v['color']}
                                        for k, v in states.items()]}}, 'overrides': []},
        'options': {'inlineEditing': False, 'panZoom': False, 'showAdvancedTypes': False,
                    'zoomToContent': True, 'tooltip': {'mode': 'single', 'disableForOneClick': False},
                    'root': {'name': 'Argo mosaic', 'type': 'frame',
                             'placement': {'width': 420, 'height': 26 + rows * 44},
                             'background': {'color': {'fixed': 'transparent'}},
                             'elements': elements}},
    })
    d['panels'].sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
