"""Configure private deployment project and scoped robots. Credentials stay on disk."""
import base64
import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.error

root = Path(sys.argv[1])
password = json.loads((root / 'private-values.json').read_text())['harborAdminPassword']
base = 'https://harbor.socrat.alchemmist.xyz/api/v2.0'
auth = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()
def api(method, path, payload=None):
    req = urllib.request.Request(base + path, method=method, headers={
        'Authorization': auth, 'Content-Type': 'application/json'},
        data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req, timeout=60) as response:
        body = response.read()
        return json.loads(body) if body else None

projects = api('GET', '/projects?name=homelab')
if not any(p['name'] == 'homelab' for p in projects):
    api('POST', '/projects', {'project_name': 'homelab', 'metadata': {'public': 'false'},
                            'storage_limit': 80 * 1024**3})
api('PUT', '/projects/homelab', {'metadata': {'public': 'false'}})
# Harbor seeds a public library project; do not leave a public default behind.
if any(p['name'] == 'library' for p in api('GET', '/projects?name=library')):
    api('PUT', '/projects/library', {'metadata': {'public': 'false'}})

for name, actions in [('ci-push', ['pull', 'push']), ('cluster-pull', ['pull'])]:
    path = root / (name + '.json')
    if path.exists():
        continue
    existing = api('GET', '/robots?page_size=100')
    if any(r['name'] == 'robot$homelab+' + name for r in existing):
        raise RuntimeError('Robot exists but local credential is missing; rotate explicitly')
    result = api('POST', '/robots', {'name': name, 'description': 'Managed homelab ' + name,
        'duration': 90, 'level': 'project', 'disable': False,
        'permissions': [{'kind': 'project', 'namespace': 'homelab',
                         'access': [{'resource': 'repository', 'action': a} for a in actions]}]})
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(result, f)
print('Private homelab project and scoped 90-day robot credentials ready.')
