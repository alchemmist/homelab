"""Upload checksum-pinned icons and change only existing applications' meta_icon."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('root', type=Path)
parser.add_argument('--public-edge')
parser.add_argument('--expected-inventory', type=Path)
args = parser.parse_args()
if args.public_edge:
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **kw: original(args.public_edge if host == 'auth.socrat.alchemmist.xyz' else host, *a, **kw)
root = args.root
assets = root / 'service-icons'
lock = open(root / 'portal-icons.lock', 'a', opener=lambda p, f: os.open(p, f, 0o600))
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
uncertain = root / 'portal-icons-uncertain.json'
if uncertain.exists():
    raise RuntimeError('Prior icon operation requires explicit receipt/state review')
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


def private_json(path, value):
    with open(path, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as out:
        json.dump(value, out)


def normalize(value, key=''):
    if isinstance(value, dict):
        return {k: normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        items = [normalize(v) for v in value]
        # Authentik list/detail endpoints return this M2M relation in different
        # orders. Preserve and compare every member, not incidental DB ordering.
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True)) if key == 'property_mappings' else items
    return value


def stable(app):
    # These three fields are the icon and its derived, possibly signed URLs.
    return normalize({k: v for k, v in app.items()
                      if k not in {'meta_icon', 'meta_icon_url', 'meta_icon_themed_urls'}})


inventory = api('GET', 'core/applications/?superuser_full_list=true&page_size=100')
if inventory['pagination']['total_pages'] != 1:
    raise RuntimeError('Incomplete application inventory; no changes made')
applications = {a['slug']: a for a in inventory['results']}
if len(applications) != len(inventory['results']):
    raise RuntimeError('Duplicate application slug')
if args.expected_inventory:
    expected = {a['slug']: a for a in json.loads(args.expected_inventory.read_text())}
    if set(expected) != set(applications) or any(
            stable(expected[s]) != stable(a) or expected[s]['meta_icon'] != a['meta_icon']
            for s, a in applications.items()):
        raise RuntimeError('Application inventory differs from reviewed audit; no changes made')

plan = []
seen = set()
for filename, source in json.loads((assets / 'sources.json').read_text())['files'].items():
    if Path(filename).name != filename or not filename.endswith('.svg'):
        raise RuntimeError('Invalid asset name')
    content = (assets / filename).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != source['sha256']:
        raise RuntimeError('Icon checksum mismatch: ' + filename)
    for node in ET.fromstring(content).iter():
        if node.tag.split('}')[-1] in {'script', 'foreignObject'} or any(
                k.lower().startswith('on') for k in node.attrib):
            raise RuntimeError('Unsafe SVG: ' + filename)
        for key, value in node.attrib.items():
            if key.split('}')[-1] == 'href' and not value.startswith(('#', 'data:image/png;base64,')):
                raise RuntimeError('External SVG resource: ' + filename)
    targets = source.get('applications', [Path(filename).stem])
    if not isinstance(targets, list):
        raise RuntimeError('Invalid icon application targets')
    name = 'service-icons/' + Path(filename).stem + '-' + digest[:12] + '.svg'
    for slug in targets:
        if not re.fullmatch(r'[a-z0-9-]+', slug) or slug in seen:
            raise RuntimeError('Invalid or duplicate application target')
        seen.add(slug)
    if targets:
        plan.append((filename, content, digest, name, targets))

run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
private_json(root / ('portal-icons-before-' + run_id + '.json'), inventory['results'])
private_json(uncertain, {'run': run_id, 'targets': sorted(seen)})
files = {f['name']: f for f in api('GET', 'admin/file/?usage=media')}
changed = []
verified = []
for filename, content, digest, name, targets in plan:
    if name not in files:
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
        files = {f['name']: f for f in api('GET', 'admin/file/?usage=media')}
    url = files[name]['url']
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'auth.socrat.alchemmist.xyz':
        raise RuntimeError('Unexpected media origin; no credential forwarding')
    # Media fetch carries no API credential, and signed URLs are never logged.
    with urllib.request.urlopen(url, timeout=60) as response:
        fetched = response.read()
    if hashlib.sha256(fetched).hexdigest() != digest:
        raise RuntimeError('Served media checksum mismatch: ' + filename)
    for slug in targets:
        if slug not in applications:
            print('Skipped nonexistent application:', slug)
            continue
        before = applications[slug]
        current = api('GET', 'core/applications/' + slug + '/')
        if stable(current) != stable(before) or current['meta_icon'] != before['meta_icon']:
            raise RuntimeError('Concurrent application change; review required: ' + slug)
        if current['meta_icon'] != name:
            # Persist a storage name, never an expiring signed URL.
            api('PATCH', 'core/applications/' + slug + '/', {'meta_icon': name})
            changed.append(slug)
        after = api('GET', 'core/applications/' + slug + '/')
        if stable(after) != stable(before) or after['meta_icon'] != name:
            raise RuntimeError('Icon-only postcondition failed: ' + slug)
        verified.append(slug)
        print('Local portal icon verified:', slug)
private_json(root / ('portal-icons-receipt-' + run_id + '.json'),
             {'run': run_id, 'changed': changed, 'verified': verified})
uncertain.unlink()
print('Completed:', len(changed), 'changed;', len(verified), 'verified; no other application fields changed')
