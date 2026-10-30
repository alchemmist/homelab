#!/usr/bin/env python3
"""Upsert inactive calendar workflow. Secrets remain outside git."""
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parents[2]
CONFIG = Path.home() / '.config/n8n'

def api(method, path, body=None):
    cmd = ['curl', '--fail-with-body', '-sS', '--resolve',
           'n8n.socrat.alchemmist.xyz:443:10.250.0.1',
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

def main():
    mapping = CONFIG / 'calendar-credentials.json'
    if not mapping.exists():
        raise RuntimeError('Create credentials in n8n and provide ~/.config/n8n/calendar-credentials.json')
    creds = json.loads(mapping.read_text())
    for kind in ('googleCalendarOAuth2Api', 'httpHeaderAuth'):
        if not creds.get(kind, {}).get('id'):
            raise RuntimeError('Missing credential mapping: ' + kind)
    w = json.loads((BASE / 'docs/n8n/calendar-voice-reminder.json').read_text())
    for n in w['nodes']:
        for kind in n.get('credentials', {}):
            n['credentials'][kind] = creds[kind]
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
