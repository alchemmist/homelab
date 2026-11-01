"""Upload checksum-pinned icons and change only existing applications' meta_icon."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import urllib.request
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('root', type=Path)
parser.add_argument('--public-edge')
args = parser.parse_args()
if args.public_edge:
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **kw: original(args.public_edge if host == 'auth.socrat.alchemmist.xyz' else host, *a, **kw)
root = args.root
assets = root / 'service-icons'
credentials = json.loads((root / 'credentials.json').read_text())
headers = {'Authorization': 'Bearer ' + credentials['AUTHENTIK_BOOTSTRAP_TOKEN']}
base = 'https://auth.socrat.alchemmist.xyz/api/v3/'
def api(method, path, payload=None):
    req = urllib.request.Request(base + path, method=method,
        headers={**headers, 'Content-Type': 'application/json'},
        data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req, timeout=60) as response:
        body = response.read()
        return json.loads(body) if body else None

existing_names = {f['name'] for f in api('GET', 'admin/file/?usage=media')}
applications = {a['slug']: a for a in api('GET', 'core/applications/?superuser_full_list=true&page_size=100')['results']}
backup = root / 'portal-icons-before-20261101.json'
if not backup.exists():
    with open(backup, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as out:
        json.dump({slug: app.get('meta_icon') for slug, app in applications.items()}, out)
for filename, source in json.loads((assets / 'sources.json').read_text())['files'].items():
    slug = Path(filename).stem
    content = (assets / filename).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != source['sha256']:
        raise RuntimeError('Icon checksum mismatch: ' + slug)
    name = 'service-icons/' + slug + '-' + digest[:12] + '.svg'
    if name not in existing_names:
        boundary = 'socrat-' + uuid.uuid4().hex
        parts = []
        for key, value in [('name', name), ('usage', 'media')]:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: image/svg+xml\r\n\r\n'.encode() + content + b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        req = urllib.request.Request(base + 'admin/file/', method='POST', data=b''.join(parts),
            headers={**headers, 'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with urllib.request.urlopen(req, timeout=60) as response:
            response.read()
    # Persist a storage name, never an expiring signed URL. Authentik resolves
    # this application metadata field to a fresh URL when serving the dashboard.
    if slug in applications:
        api('PATCH', 'core/applications/' + slug + '/', {'meta_icon': name})
    print('Local portal icon reconciled:', slug)
