#!/usr/bin/env python3
import json
import sys

import yaml


DASHBOARD_UID = 'rancher-cluster-nodes-1'
NODE_NAMES = 'max by (instance, nodename) (node_uname_info{job="node-exporter"})'


def panels(dashboard):
    for panel in dashboard.get('panels', []):
        yield panel
        yield from panels(panel)


def main():
    manifests = list(yaml.safe_load_all(sys.stdin))
    found = False
    for manifest in manifests:
        if not manifest or manifest.get('kind') != 'ConfigMap':
            continue
        if manifest.get('metadata', {}).get('name') != 'rancher-default-dashboards-cluster':
            continue
        for name, content in manifest.get('data', {}).items():
            if not name.endswith('.json'):
                continue
            dashboard = json.loads(content)
            if dashboard.get('uid') != DASHBOARD_UID:
                continue
            found = True
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
    if not found:
        raise RuntimeError('The Rancher node dashboard was not found in the pinned chart')
    yaml.safe_dump_all(manifests, sys.stdout, sort_keys=False)


if __name__ == '__main__':
    main()
