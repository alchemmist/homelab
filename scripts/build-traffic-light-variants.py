#!/usr/bin/env python3
"""Build native Grafana alternatives without modifying the canonical TV dashboard."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
OUTPUT = ROOT / 'prototypes/traffic-light'
VARIANTS = {
    1: 'Top labels',
    2: 'Vertical bars',
    3: 'Compact stats',
    4: 'Quiet bars',
}


def build(source, number):
    dashboard = copy.deepcopy(source)
    dashboard.pop('id', None)
    dashboard['uid'] = f'socrat-traffic-light-tmp-{number}'
    dashboard['title'] = f'TMP-{number} Traffic Light — {VARIANTS[number]}'
    dashboard['version'] = 0
    dashboard['tags'] = list(dict.fromkeys(dashboard.get('tags', []) + ['traffic-light-preview']))
    dashboard['description'] = 'Temporary native visualization comparison; original TV dashboard and public share are unchanged.'
    for panel in dashboard['panels']:
        if panel['id'] not in (21, 22, 23):
            continue
        options = panel['options']
        options['namePlacement'] = 'top'
        options['text'] = {'titleSize': 16, 'valueSize': 16}
        if number == 2:
            options['orientation'] = 'vertical'
            options['namePlacement'] = 'auto'
            options['text'] = {'titleSize': 14, 'valueSize': 16}
        elif number == 3:
            panel['type'] = 'stat'
            panel['options'] = {
                'reduceOptions': options['reduceOptions'],
                'orientation': 'horizontal', 'textMode': 'value_and_name',
                'colorMode': 'value', 'graphMode': 'none',
                'justifyMode': 'auto', 'wideLayout': False,
                'text': {'titleSize': 16, 'valueSize': 24},
            }
        elif number == 4:
            options['valueMode'] = 'hidden'
            panel['description'] += ' Preview: absolute usage is available on hover; bars retain per-node capacity and relative thresholds.'
    return dashboard


def main():
    source = json.loads(SOURCE.read_text())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for number in VARIANTS:
        dashboard = build(source, number)
        (OUTPUT / f'tmp-{number}.json').write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + '\n')
    print('Built four importable dashboards; no live writes performed.')


if __name__ == '__main__':
    main()
