#!/usr/bin/env python3
"""Replace raw authorization-flow title placeholders, not authentication behavior."""
import argparse
import json
import os
from pathlib import Path
import socket
import urllib.request

TITLES = {
    'default-provider-authorization-explicit-consent': 'Redirecting',
    'default-provider-authorization-implicit-consent': 'Redirecting',
}


def reconcile(api, root, rollback=False):
    backup = root / 'authorization-flow-titles-original.json'
    current = {slug: api('GET', 'flows/instances/' + slug + '/') for slug in TITLES}
    if rollback:
        original = json.loads(backup.read_text())
        desired = {slug: original[slug]['title'] for slug in TITLES}
        if any(current[slug]['pk'] != original[slug]['pk'] for slug in TITLES):
            raise RuntimeError('Flow identity changed; refusing automatic rollback')
    else:
        desired = TITLES
        if not backup.exists():
            with open(backup, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
                json.dump({slug: {'pk': row['pk'], 'title': row['title']} for slug, row in current.items()}, stream, indent=2)
    changed = []
    try:
        for slug, title in desired.items():
            if current[slug]['title'] != title:
                api('PATCH', 'flows/instances/' + slug + '/', {'title': title})
                changed.append(slug)
    except Exception:
        for slug in changed:
            api('PATCH', 'flows/instances/' + slug + '/', {'title': current[slug]['title']})
        raise
    return bool(changed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--public-edge', default='109.173.40.247')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **kw: original(args.public_edge if host == 'auth.socrat.alchemmist.xyz' else host, *a, **kw)
    credential = json.loads((args.root / 'credentials.json').read_text())
    def api(method, path, value=None):
        req = urllib.request.Request('https://auth.socrat.alchemmist.xyz/api/v3/' + path, method=method,
            headers={'Authorization': 'Bearer ' + credential['AUTHENTIK_BOOTSTRAP_TOKEN'], 'Content-Type': 'application/json'},
            data=json.dumps(value).encode() if value is not None else None)
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response)
    if not args.rollback and api('GET', 'admin/version/')['version_current'] != '2026.8.5':
        raise RuntimeError('Unreviewed Authentik version')
    changed = reconcile(api, args.root, args.rollback)
    print('Authorization flow titles updated' if changed else 'Authorization flow titles already reconciled')


if __name__ == '__main__':
    main()
