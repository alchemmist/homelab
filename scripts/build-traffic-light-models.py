#!/usr/bin/env python3
"""Two TV model timelines; preserve owner deletions/layout and Argo bottom boundary."""
import copy
import json
import runpy
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'charts/monitoring-k3s/dashboards/traffic-light.json'
IDS = {937, 938}


def build(source=None):
    d = copy.deepcopy(source if source is not None else json.loads(SOURCE.read_text()))
    owner = {p['id']: p for p in d['panels']}
    bottom = owner[909]['gridPos']['y'] + owner[909]['gridPos']['h']
    keys = json.loads((SOURCE.parent / 'llm-keys.json').read_text())
    for pid, template, title, pos in [
        (937, keys['panels'][0], 'qwen3.8-27b', dict(x=6,y=14,w=6,h=5)),
        (938, keys['panels'][1], 'venice-deepseek', dict(x=16,y=16,w=8,h=4)),
    ]:
        p = copy.deepcopy(template)
        p.update(id=pid, title=title, gridPos=copy.deepcopy(owner[pid]['gridPos']) if pid in owner else pos)
        p.pop('timeFrom', None)
        p.pop('hideTimeOverride', None)
        p['interval'] = '1m'
        p['maxDataPoints'] = 720
        p['options']['legend'] = {'showLegend': False, 'calcs': [], 'displayMode': 'list', 'placement': 'bottom'}
        p['fieldConfig']['defaults']['custom'].update(axisLabel='', axisBorderShow=False, axisGridShow=True, lineWidth=1, fillOpacity=8)
        p['description'] += ' TV: same time range as dashboard (default12h); no legend, native hover retains alias. Requests per rolling minute, not in-flight concurrency.'
        d['panels'] = [v for v in d['panels'] if v['id'] != pid] + [p]
    occupied = set()
    for p in d['panels']:
        g = p['gridPos']
        cells = {(x,y) for x in range(g['x'],g['x']+g['w']) for y in range(g['y'],g['y']+g['h'])}
        if cells & occupied or not(0 <= g['x'] < g['x']+g['w'] <= 24 and 0 <= g['y'] < g['y']+g['h'] <= bottom):
            raise ValueError('Overlap or Argo bottom boundary exceeded; preserve owner layout and stop')
        occupied |= cells
    return d


def write(d):
    # Preserve existing owned-widget compaction and actual ConfigMap size budget.
    quality = runpy.run_path(str(SOURCE.parents[3] / 'scripts/build-traffic-light-quality.py'))
    quality['write'](d)
    text = SOURCE.read_text()
    for p in d['panels']:
        if p['id'] not in IDS | {909}:
            continue
        block = '\n'.join('    '+line for line in json.dumps(p,ensure_ascii=False,indent=2).splitlines())
        assert text.count(block) == 1
        text = text.replace(block,'    '+json.dumps(p,ensure_ascii=False,separators=(',',':')),1)
    SOURCE.write_text(text)


if __name__ == '__main__':
    write(build())
