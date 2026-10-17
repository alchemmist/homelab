#!/usr/bin/env python3
import json
import sys

import yaml


DASHBOARD_UID = 'rancher-cluster-nodes-1'
RANCHER_DASHBOARD_UIDS = {
    'rancher-home-1',
    'rancher-cluster-1',
    'rancher-cluster-nodes-1',
    'rancher-etcd-1',
    'rancher-etcd-nodes-1',
    'rancher-k8s-components-1',
    'rancher-k8s-components-nodes-1',
    'rancher-node-1',
    'rancher-node-detail-1',
    'rancher-pod-1',
    'rancher-pod-containers-1',
    'rancher-workload-1',
    'rancher-workload-pods-1',
}
NODE_NAMES = 'max by (instance, nodename) (node_uname_info{job="node-exporter"})'

NODE_DASHBOARD_UIDS = {'rancher-node-1', 'rancher-node-detail-1'}
EXPORTER_QUERY = (
    'query_result(label_replace(node_uname_info{job="node-exporter"}, '
    '"node_ip", "$1", "instance", "(.+):[0-9]+") and on (node_ip) '
    'label_replace(label_replace(vector(1), "node_ip", "$instance", "", ""), '
    '"node_ip", "$1", "node_ip", "(.+):[0-9]+"))'
)

CPU_TEMPERATURE_PANEL_ID = 1001
CPU_TEMPERATURE_BASE = (
    '(avg by (instance, chip, sensor) (node_hwmon_temp_celsius{job="node-exporter",instance="$exporter_instance"}) '
    '* on (instance, chip) group_left (chip_name) '
    'max by (instance, chip, chip_name) (node_hwmon_chip_names{job="node-exporter",chip_name=~"coretemp|k10temp|zenpower"}))'
)
CPU_SENSOR_LABELS = 'max by (instance, chip, sensor, label) (node_hwmon_sensor_label{job="node-exporter"})'
CPU_TEMPERATURE_QUERY = (
    '(' + CPU_TEMPERATURE_BASE + ' * on (instance, chip, sensor) group_left (label) '
    + CPU_SENSOR_LABELS + ') or label_replace(('
    + CPU_TEMPERATURE_BASE + ' unless on (instance, chip, sensor) '
    + CPU_SENSOR_LABELS + '), "label", "$1", "sensor", "(.+)")'
)


def add_cpu_temperature(dashboard):
    existing = next((p for p in dashboard['panels'] if p['id'] == CPU_TEMPERATURE_PANEL_ID), None)
    position = existing['gridPos'] if existing else {
        'x': 0, 'y': max(p['gridPos']['y'] + p['gridPos']['h'] for p in dashboard['panels']),
        'w': 24, 'h': 10,
    }
    dashboard['panels'] = [p for p in dashboard['panels'] if p['id'] != CPU_TEMPERATURE_PANEL_ID]
    dashboard['panels'].append({
        'id': CPU_TEMPERATURE_PANEL_ID,
        'title': 'CPU temperature',
        'description': 'Individual core and package/control temperatures where hardware exposes them. AMD systems may provide only shared CPU sensors. VPS hosts usually expose no sensors. Missing data does not mean 0 °C. GPU and disk sensors are excluded.',
        'type': 'timeseries',
        'gridPos': position,
        'datasource': {'type': 'prometheus', 'uid': '${datasource}'},
        'targets': [{'refId': 'A', 'expr': CPU_TEMPERATURE_QUERY,
                     'legendFormat': '{{chip_name}} · {{label}} · {{chip}}/{{sensor}}', 'range': True}],
        'fieldConfig': {'defaults': {
            'unit': 'celsius', 'decimals': 1,
            'color': {'mode': 'palette-classic'},
            'custom': {'drawStyle': 'line', 'lineWidth': 1, 'fillOpacity': 0,
                       'showPoints': 'never', 'spanNulls': False},
        }, 'overrides': []},
        'options': {
            'legend': {'displayMode': 'table', 'placement': 'right', 'calcs': ['lastNotNull', 'max']},
            'tooltip': {'mode': 'multi', 'sort': 'desc'},
        },
    })


def resolve_node_exporter(dashboard):
    variables = dashboard.setdefault('templating', {}).setdefault('list', [])
    variables[:] = [v for v in variables if v.get('name') != 'exporter_instance']
    variables.append({
        'name': 'exporter_instance',
        'label': 'Exporter instance',
        'type': 'query',
        'hide': 2,
        'datasource': {'type': 'prometheus', 'uid': '${datasource}'},
        'query': {'query': EXPORTER_QUERY, 'refId': 'nodeExporterInstance'},
        'definition': EXPORTER_QUERY,
        'regex': '/(?:^|[,{ ])instance="([^"]+)"/',
        'refresh': 1,
        'sort': 1,
        'multi': False,
        'includeAll': False,
        'options': [],
    })
    for panel in panels(dashboard):
        for target in panel.get('targets', []):
            if 'expr' in target:
                target['expr'] = target['expr'].replace('$instance', '$exporter_instance')
                if dashboard['uid'] == 'rancher-node-detail-1' and panel.get('id') == 4:
                    target['expr'] = 'avg(' + target['expr'].strip() + ')'


def panels(dashboard):
    for panel in dashboard.get('panels', []):
        yield panel
        yield from panels(panel)


def main():
    manifests = list(yaml.safe_load_all(sys.stdin))
    found = set()
    for manifest in manifests:
        if not manifest or manifest.get('kind') != 'ConfigMap':
            continue
        dashboard_uids = set()
        for name, content in manifest.get('data', {}).items():
            if not name.endswith('.json'):
                continue
            dashboard = json.loads(content)
            uid = dashboard.get('uid')
            if not uid:
                continue
            dashboard_uids.add(uid)
            if uid in RANCHER_DASHBOARD_UIDS:
                found.add(uid)
                title = dashboard['title'].removeprefix('Rancher / ').removeprefix('[Rancher] ')
                dashboard['title'] = title
                manifest['data'][name] = json.dumps(dashboard, ensure_ascii=False, separators=(',', ':'))
            if uid in NODE_DASHBOARD_UIDS:
                resolve_node_exporter(dashboard)
                add_cpu_temperature(dashboard)
                manifest['data'][name] = json.dumps(dashboard, ensure_ascii=False, separators=(',', ':'))
            if uid != DASHBOARD_UID:
                continue
            for panel in panels(dashboard):
                for target in panel.get('targets', []):
                    legend = target.get('legendFormat', '')
                    if '{{instance}}' not in legend:
                        continue
                    target['expr'] = '(' + target['expr'].strip() + ') * on (instance) group_left (nodename) ' + NODE_NAMES
                    target['legendFormat'] = legend.replace('{{instance}}', '{{nodename}}')
                for override in panel.get('fieldConfig', {}).get('overrides', []):
                    matcher = override.get('matcher', {})
                    if matcher.get('id') == 'byName' and isinstance(matcher.get('options'), str):
                        matcher['options'] = matcher['options'].replace('{{instance}}', '{{nodename}}')
            manifest['data'][name] = json.dumps(dashboard, ensure_ascii=False, separators=(',', ':'))
        if dashboard_uids:
            embedded = dashboard_uids & RANCHER_DASHBOARD_UIDS
            if embedded and embedded != dashboard_uids:
                raise RuntimeError('Embedded and diagnostic dashboards share a ConfigMap')
            folder = 'Rancher' if embedded else 'Kubernetes Diagnostics'
            metadata = manifest.setdefault('metadata', {})
            metadata['annotations'] = metadata.get('annotations') or {}
            metadata['annotations']['grafana_folder'] = '/tmp/dashboards/' + folder
    if found != RANCHER_DASHBOARD_UIDS:
        raise RuntimeError('The pinned chart is missing Rancher dashboards: ' + ', '.join(sorted(RANCHER_DASHBOARD_UIDS - found)))
    yaml.safe_dump_all(manifests, sys.stdout, sort_keys=False)


if __name__ == '__main__':
    main()
