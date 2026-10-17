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
                dashboard['title'] = '[Rancher] ' + title
                manifest['data'][name] = json.dumps(dashboard, ensure_ascii=False, separators=(',', ':'))
            if uid in NODE_DASHBOARD_UIDS:
                resolve_node_exporter(dashboard)
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
            folder = 'Rancher' if embedded else 'Диагностика Kubernetes'
            metadata = manifest.setdefault('metadata', {})
            metadata['annotations'] = metadata.get('annotations') or {}
            metadata['annotations']['grafana_folder'] = '/tmp/dashboards/' + folder
    if found != RANCHER_DASHBOARD_UIDS:
        raise RuntimeError('The pinned chart is missing Rancher dashboards: ' + ', '.join(sorted(RANCHER_DASHBOARD_UIDS - found)))
    yaml.safe_dump_all(manifests, sys.stdout, sort_keys=False)


if __name__ == '__main__':
    main()
