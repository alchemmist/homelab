#!/usr/bin/env python3
"""Upsert inactive calendar workflow. Secrets remain outside git."""
import copy
import os
import re
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parents[2]
CONFIG = Path.home() / '.config/n8n'

def api(method, path, body=None):
    cmd = ['curl', '--fail-with-body', '-sS', '--connect-timeout', '5', '--max-time', '30', '--resolve',
           'n8n.socrat.alchemmist.xyz:443:' + os.environ.get('N8N_API_RESOLVE_ADDRESS', '10.250.0.1'),
           '-X', method, '-H', 'X-N8N-API-KEY: ' + (CONFIG / 'api-key').read_text().strip(),
           '-H', 'Content-Type: application/json',
           'https://n8n.socrat.alchemmist.xyz/api/v1/' + path]
    if body is not None:
        cmd += ['--data-binary', '@-']
    r = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                       text=True, capture_output=True)
    if r.returncode:
        raise RuntimeError('API request failed: ' + method + ' ' + path)
    return json.loads(r.stdout) if r.stdout else {}

def render_workflow(template, creds, calendar, cloud=None):
    for kind in {k for n in template['nodes'] for k in n.get('credentials', {})}:
        if not creds.get(kind, {}).get('id'):
            raise RuntimeError('Missing credential mapping: ' + kind)
    ids = calendar.get('calendar_ids', ['primary'])
    if not isinstance(ids, list) or not ids or not all(isinstance(x, str) and x for x in ids):
        raise RuntimeError('calendar_ids must be a nonempty list of calendar IDs')
    w = copy.deepcopy(template)
    for n in w['nodes']:
        if n['name'] == 'Select Calendars':
            n['parameters']['jsCode'] = 'return ' + json.dumps(ids) + '.map(calendarId => ({ json: { calendarId } }));'
        for kind in n.get('credentials', {}):
            n['credentials'][kind] = creds[kind]
    require_yandex_policy(w)
    return w

def require_yandex_policy(workflow):
    for node in workflow['nodes']:
        if node['type'] == 'CUSTOM.yandexStation':
            if set(node.get('credentials', {})) != {'yandexStationApi'}:
                raise RuntimeError('Automatic Yandex node requires encrypted x-token credentials')
        if node['type'] != 'n8n-nodes-base.httpRequest':
            continue
        params = node.get('parameters', {})
        url = urlsplit(params.get('url', ''))
        if (url.scheme != 'https' or url.netloc != 'api.iot.yandex.net'
                or params.get('genericAuthType') != 'httpHeaderAuth'
                or params.get('method') != 'POST'
                or not re.fullmatch(r'/v1[.]0/scenarios/[A-Za-z0-9_-]+/actions', url.path)
                or url.query or url.fragment):
            raise RuntimeError('Only public Yandex scenario execution with token credentials is allowed')


def main():
    mapping = CONFIG / 'calendar-credentials.json'
    if not mapping.exists():
        raise RuntimeError('Create credentials in n8n and provide ~/.config/n8n/calendar-credentials.json')
    creds = json.loads(mapping.read_text())
    calendar_config = CONFIG / 'calendar-config.json'
    calendar = json.loads(calendar_config.read_text()) if calendar_config.exists() else {}
    template = json.loads((BASE / 'docs/n8n/calendar-voice-reminder.json').read_text())
    require_yandex_policy(template)
    w = render_workflow(template, creds, calendar)
    body = {k: w[k] for k in ['name', 'nodes', 'connections', 'settings']}
    existing = [x for x in api('GET', 'workflows?limit=250')['data'] if x['name'] == w['name']]
    if len(existing) > 1:
        raise RuntimeError('Duplicate workflow names; refusing to update')
    if existing and existing[0]['active']:
        raise RuntimeError('Workflow is active; deactivate explicitly before sync')
    result = api('PUT' if existing else 'POST',
                 'workflows/' + existing[0]['id'] if existing else 'workflows', body)
    print('Workflow:', result['id'], 'active:', result.get('active', False))
    print('Google credential:', creds['googleCalendarOAuth2Api']['id'])

if __name__ == '__main__':
    main()
