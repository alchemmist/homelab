import json
from functools import lru_cache
from pathlib import Path


PANEL_UNITS = {
    '3e97d1d02672cdd0861f4c97c64f89b2': {9: 'pps', 12: 'short'},
    'fac67cfbe174d3ef53eb473d73d9212f': {9: 'pps', 12: 'short'},
    '6be0s85Mk': {4: 's'},
    'vkQ0UHxik': {22: 'short'},
}


@lru_cache(maxsize=1)
def load_descriptions():
    descriptions = {}
    for path in sorted(Path(__file__).with_name('dashboard-descriptions').glob('*.json')):
        entries = json.loads(path.read_text())
        overlap = descriptions.keys() & entries.keys()
        if overlap:
            raise ValueError('Duplicate dashboard descriptions: ' + ', '.join(sorted(overlap)))
        descriptions.update(entries)
    return descriptions


def panels(dashboard):
    for panel in dashboard.get('panels', []):
        if panel.get('type') not in {'row', 'text'}:
            yield panel
        yield from panels(panel)


def apply_descriptions(dashboard, descriptions=None):
    catalog = load_descriptions() if descriptions is None else descriptions
    uid = dashboard['uid']
    entries = catalog.get(uid, {})
    for panel in panels(dashboard):
        description = entries.get(str(panel['id']))
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f'Missing description for dashboard {uid}, panel {panel["id"]}')
        panel['description'] = description
        unit = PANEL_UNITS.get(uid, {}).get(panel['id'])
        if unit:
            panel.setdefault('fieldConfig', {}).setdefault('defaults', {})['unit'] = unit
