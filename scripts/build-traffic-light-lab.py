#!/usr/bin/env python3
"""Build the native-only TMP lab. Never edits the canonical dashboard."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
OUTPUT = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light-tmp-lab.json'
DS = {'type': 'prometheus', 'uid': 'prometheus'}
GREEN, ORANGE, RED, GREY = '#73BF69', '#FFB357', '#F2495C', '#808080'


def target(expr, legend='', instant=True):
    return dict(datasource=DS, expr=expr, legendFormat=legend, refId='A',
                instant=instant, range=not instant, format='time_series')


def grid(x, y, w, h):
    return dict(x=x, y=y, w=w, h=h)


def fresh(metric, selector):
    return f'({metric}{{{selector}}} and (time() - timestamp({metric}{{{selector}}}) < 90))'


def build():
    source = json.loads(SOURCE.read_text())
    d = copy.deepcopy(source)
    d.pop('id', None)
    d.pop('version', None)
    d.update(uid='socrat-traffic-light-tmp-lab', title='Traffic Light · TMP Lab',
             description='Private sandbox: Argo attention board, LiteLLM usage and infrastructure readiness. Canonical TV dashboard is unchanged.',
             tags=source.get('tags', []) + ['temporary', 'sandbox'])
    panels = {p['id']: p for p in d['panels']}
    d['panels'] = [p for p in d['panels'] if p['id'] != 909]
    tile = panels[901]

    def stat(pid, name, expr, pos, color=None, unit='short', title='', description=''):
        p = copy.deepcopy(tile)
        p.update(id=pid, title=title, description=description, gridPos=pos)
        p['targets'] = [target(expr, name)]
        defaults = p['fieldConfig']['defaults']
        defaults.update(displayName=name, unit=unit, decimals=0,
                        mappings=[{'type': 'special', 'options': {'match': 'null+nan', 'result': {'text': 'No telemetry', 'color': GREY}}}],
                        noValue='No telemetry')
        defaults['thresholds'] = {'mode': 'absolute', 'steps': [{'color': GREEN, 'value': None}, {'color': RED, 'value': 1}]}
        if color:
            defaults['color'] = {'mode': 'fixed', 'fixedColor': color}
        else:
            defaults['color'] = {'mode': 'thresholds'}
        p['options'].update(textMode='value_and_name', colorMode='value', orientation='horizontal',
                            text={'titleSize': 13, 'valueSize': 30})
        d['panels'].append(p)
        return p

    argo = fresh('argocd_app_info', 'job="socrat-argocd"')
    gate = '(max(up{job="socrat-argocd"} == 1 and (time() - timestamp(up{job="socrat-argocd"}) < 90)) == 1)'
    total = f'count({argo})'
    def count_status(selector):
        selected = fresh('argocd_app_info', f'job="socrat-argocd",{selector}')
        return f'((count({selected}) or (0 * {total})) and on() {gate})'

    stat(950, 'Argo · ready', count_status('sync_status="Synced",health_status="Healthy"'),
         grid(12, 8, 2, 2), GREEN, description='Applications both Synced and Healthy now. Missing or stale collector data is not a healthy zero.')
    stat(951, 'Git · drift', count_status('sync_status!="Synced"'), grid(14, 8, 2, 2),
         description='Applications not Synced, including unknown sync status. This is drift, not necessarily a service outage.')
    attention = stat(952, 'Apps · attention', count_status('health_status!="Healthy"'), grid(16, 8, 2, 2),
                     description='Non-Healthy applications, including Progressing and Suspended. Inspect the table below; not every attention state is a failure.')
    attention['fieldConfig']['defaults']['thresholds']['steps'][1]['color'] = ORANGE

    # Native table: current named exceptions, with a fresh healthy sentinel.
    bad = f'(({argo}) and on(name) (argocd_app_info{{job="socrat-argocd",sync_status!="Synced"}} or argocd_app_info{{job="socrat-argocd",health_status!="Healthy"}}))'
    query = f'(topk(3, max by(name,health_status,sync_status) ({bad})) or label_replace((0 * {total}) unless on() count({bad}), "name", "All apps healthy + synced", "", "")) and on() {gate}'
    table = dict(id=953, title='Argo · attention now', type='table', datasource=DS, gridPos=grid(12, 10, 6, 2),
                 description='Up to three affected apps. Status names identify where to investigate, not a root-cause diagnosis. Counters above include all apps. Click through to Argo CD for events and details.',
                 targets=[dict(target(query), format='table')],
                 transformations=[{'id': 'organize', 'options': {
                     'excludeByName': {'Time': True, 'Value': True, '__name__': True},
                     'indexByName': {'name': 0, 'sync_status': 1, 'health_status': 2},
                     'renameByName': {'name': 'Application', 'sync_status': 'Git', 'health_status': 'Health'}}}],
                 fieldConfig={'defaults': {'noValue': '—', 'custom': {'align': 'left', 'cellOptions': {'type': 'auto'}},
                                          'links': [{'title': 'Open Argo CD', 'url': 'https://argocd.socrat.alchemmist.xyz/applications', 'targetBlank': True}]},
                              'overrides': [{'matcher': {'id': 'byRegexp', 'options': 'Git|Health'}, 'properties': [
                                  {'id': 'custom.cellOptions', 'value': {'type': 'color-background'}},
                                  {'id': 'mappings', 'value': [{'type': 'value', 'options': {
                                      'Synced': {'text': 'Synced', 'color': GREEN}, 'Healthy': {'text': 'Healthy', 'color': GREEN},
                                      'OutOfSync': {'text': 'Drift', 'color': ORANGE}, 'Progressing': {'text': 'Progressing', 'color': '#5794F2'},
                                      'Suspended': {'text': 'Paused', 'color': ORANGE}, 'Degraded': {'text': 'Degraded', 'color': RED},
                                      'Missing': {'text': 'Missing', 'color': RED}, 'Unknown': {'text': 'Unknown', 'color': GREY}}}]}]}]},
                 options={'showHeader': False, 'cellHeight': 'sm', 'footer': {'show': False}})
    d['panels'].append(table)

    llm_gate = '(max(up{job="litellm"} == 1 and (time() - timestamp(up{job="litellm"}) < 90)) == 1)'
    alias = 'api_key_alias!~"None|null|^$"'
    tokens = f'topk(4, sum by(api_key_alias) (increase(litellm_total_tokens_metric_total{{{alias}}}[24h]))) and on() {llm_gate}'
    p = copy.deepcopy(panels[21])
    p.update(id=954, title='LiteLLM · tokens by key · 24h', type='bargauge', gridPos=grid(12, 12, 6, 3),
             description='Top four named virtual keys by input + output tokens over rolling 24h. Usage is not money and aliases are not necessarily people. Includes cached input and provider accounting semantics. Prometheus increase is an estimate; no database billing reconciliation. Unnamed aliases excluded. Private lab only: never public-shared automatically.')
    p.pop('transformations', None)
    p['targets'] = [target(tokens, '{{api_key_alias}}')]
    p['fieldConfig'] = {'defaults': {'min': 0, 'unit': 'short', 'decimals': 1, 'noValue': 'No usage telemetry',
                                    'color': {'mode': 'palette-classic'}, 'mappings': []}, 'overrides': []}
    p['options'] = {'orientation': 'horizontal', 'displayMode': 'basic', 'namePlacement': 'top',
                    'valueMode': 'text', 'showUnfilled': False, 'sizing': 'auto',
                    'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                    'text': {'titleSize': 13, 'valueSize': 17}}
    d['panels'].append(p)
    coverage = fresh('litellm_spend_capture_rate', '')
    # Count comparison also rejects partially stale or NaN provider coverage.
    priced = f'(count(({coverage} >= 1) and ({coverage} <= 1)) == count(litellm_spend_capture_rate))'
    money = f'sum(increase(litellm_spend_metric_total[24h])) and on() {llm_gate} and on() {priced}'
    p = stat(955, 'USD · 24h', money, grid(12, 15, 3, 1), GREY, 'currencyUSD',
             description='Reported 24h spend, shown only when all emitted provider capture ratios are fresh and equal to 1. Currently zero spend counters + NaN capture ratio: pricing is unverified, not proven free usage. Even valid ratios are not invoice reconciliation.')
    p['fieldConfig']['defaults'].update(noValue='Unverified', decimals=2)
    p['fieldConfig']['defaults']['mappings'][0]['options']['result']['text'] = 'Unverified'
    requests = f'sum(increase(litellm_proxy_total_requests_metric_total[24h])) and on() {llm_gate}'
    stat(956, 'Requests · 24h', requests, grid(15, 15, 3, 1), '#8AB8FF',
         description='Estimated client proxy requests over rolling 24h, including unnamed keys; not provider retries. Rolling history remains informative overnight.')

    def readiness(pid, name, namespace, deployment, pos):
        selector = f'namespace="{namespace}",deployment="{deployment}"'
        available = fresh('kube_deployment_status_replicas_available', selector)
        desired = fresh('kube_deployment_spec_replicas', selector)
        query = f'((max({available}) < bool max({desired})) or vector(-2))'
        p = stat(pid, name, query, pos, description=f'Deployment readiness only: {namespace}/{deployment}. Green = available replicas meet desired and desired > 0; orange = not ready or scaled off; grey = stale/missing. NOT an end-to-end S3 request, authenticated download or VPN data-path/native-fallback test.')
        p['targets'] = [target(f'((clamp_max((max({available}) < bool max({desired})) + (max({desired}) == bool 0), 1)) or vector(-2))', name)]
        p['options'].update(colorMode='background_solid', textMode='name', text={'titleSize': 14})
        p['fieldConfig']['defaults']['mappings'] = [{'type': 'value', 'options': {
            '0': {'text': 'Ready', 'color': '#26783D'}, '1': {'text': 'Not ready', 'color': ORANGE}, '-2': {'text': 'No telemetry', 'color': '#555555'}}}]
        return p
    readiness(957, 'RustFS', 'rustfs', 'rustfs', grid(6, 6, 3, 1))
    readiness(958, 'VPN relay · MSK', 'vpn-transit', 'vpn-transit', grid(6, 7, 3, 1))
    readiness(959, 'S3 reader', 'identity', 'rustfs-gateway', grid(0, 11, 2, 1))
    stat(960, 'LLM · req/5m', f'sum(increase(litellm_proxy_total_requests_metric_total[5m])) and on() {llm_gate}',
         grid(2, 11, 2, 1), '#B877D9', description='Estimated client requests in the last five minutes. Zero with fresh scrape is valid quiet time; absent scrape is No telemetry.')
    d['panels'].sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
    return d


if __name__ == '__main__':
    OUTPUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n')
    print(OUTPUT.relative_to(ROOT))
