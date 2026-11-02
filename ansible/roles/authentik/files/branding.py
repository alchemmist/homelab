#!/usr/bin/env python3
"""Reconcile Quiet Mono Brand assets/CSS only; never replace authentication code.
Run as the owner with credentials in the protected Authentik deployment directory.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import urllib.parse
import urllib.request

HOST = 'auth.socrat.alchemmist.xyz'
BASE = 'https://' + HOST
FIELDS = ('domain', 'default', 'branding_title', 'branding_logo', 'branding_favicon',
          'branding_default_flow_background', 'branding_custom_css', 'attributes',
          'default_application', 'flow_authentication', 'flow_invalidation',
          'flow_recovery', 'flow_unenrollment', 'flow_user_settings', 'flow_device_code',
          'flow_user_switch', 'flow_lockdown', 'flow_request', 'web_certificate',
          'client_certificates')


def protected_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, 'w', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(value, stream, indent=2)
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('theme', type=Path)
    parser.add_argument('--action', choices=['prepare', 'apply', 'rollback'], default='prepare')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--public-edge', help='Process-local resolution only; TLS/SNI stays verified')
    args = parser.parse_args()
    if args.public_edge:
        original = socket.getaddrinfo
        socket.getaddrinfo = lambda host, *a, **kw: original(args.public_edge if host == HOST else host, *a, **kw)
    credentials = json.loads((args.root / 'credentials.json').read_text())
    headers = {'Authorization': 'Bearer ' + credentials['AUTHENTIK_BOOTSTRAP_TOKEN']}

    def api(method, path, data=None):
        request = urllib.request.Request(BASE + '/api/v3/' + path, method=method,
            headers={**headers, 'Content-Type': 'application/json'},
            data=json.dumps(data).encode() if data is not None else None)
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            return json.loads(body) if body else None

    def exact_brand():
        rows = api('GET', 'core/brands/?page_size=100')['results']
        matches = [row for row in rows if row['domain'] == HOST]
        if len(matches) > 1:
            raise RuntimeError('Ambiguous domain brand; refusing to change it')
        return rows, matches[0] if matches else None

    if args.action != 'rollback' and api('GET', 'admin/version/').get('version_current') != '2026.8.5':
        raise RuntimeError('Theme requires reviewed Authentik 2026.8.5; refusing version drift')
    journal_path = args.root / 'quiet-mono-brand-journal.json'
    if args.action == 'rollback':
        if not args.backup:
            raise RuntimeError('Explicit --backup required for rollback')
        backup = json.loads(args.backup.read_text())
        _, current = exact_brand()
        if backup['brand_before']:
            if not current or current['brand_uuid'] != backup['brand_before']['brand_uuid']:
                raise RuntimeError('Brand identity changed; manual review required')
            api('PATCH', 'core/brands/' + current['brand_uuid'] + '/',
                {key: backup['brand_before'][key] for key in FIELDS if key in backup['brand_before']})
        elif current:
            journal = json.loads(journal_path.read_text())
            if current['brand_uuid'] != journal['brand_uuid']:
                raise RuntimeError('Refusing to remove an unrelated brand')
            api('DELETE', 'core/brands/' + current['brand_uuid'] + '/')
        flow = backup['flow_before']
        api('PATCH', 'flows/instances/' + flow['slug'] + '/', {'title': flow['title']})
        if backup.get('identification_before'):
            stage = backup['identification_before']
            api('PATCH', 'stages/identification/' + stage['pk'] + '/', {'password_stage': stage['password_stage'], 'user_fields': stage['user_fields']})
        if backup.get('password_before'):
            stage = backup['password_before']
            api('PATCH', 'stages/password/' + stage['pk'] + '/', {'allow_show_password': stage['allow_show_password']})
        print('Brand and native display settings restored; no user/provider/session changes')
        return

    assets = json.loads((args.theme / 'assets.json').read_text())
    urls = {}
    for key, asset in assets.items():
        path = args.theme / asset['path']
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != asset['sha256']:
            raise RuntimeError('Asset checksum mismatch: ' + key)
        # Do not persist Authentik media JWT URLs in CSS: those expire.
        url = BASE + '/-/quiet-mono/v1/' + digest[:12] + '-' + path.name
        with urllib.request.urlopen(url, timeout=60) as response:
            if hashlib.sha256(response.read()).hexdigest() != digest:
                raise RuntimeError('Public static asset verification failed: ' + key)
        urls[key] = url
    if (args.theme / 'nature.json').exists():
        for variant in ['desktop', 'mobile']:
            url = BASE + '/-/quiet-mono/v1/nature/' + variant
            with urllib.request.urlopen(url, timeout=60) as response:
                digest = hashlib.sha256(response.read()).hexdigest()
                allowed = {assets[p[variant]]['sha256'] for p in json.loads((args.theme / 'nature.json').read_text())['photos']}
                if digest not in allowed or 'immutable' not in response.headers.get('Cache-Control', ''):
                    raise RuntimeError('Random Nature response failed verification')
            urls['NATURE_RANDOM_' + variant.upper()] = url
    if (args.theme / 'nature.json').exists():
        scene_url = BASE + '/-/quiet-mono/v1/nature/scene.css'
        with urllib.request.urlopen(scene_url,timeout=60) as response:
            allowed_css={assets[p['sceneCss']]['sha256'] for p in json.loads((args.theme/'nature.json').read_text())['photos']}
            if hashlib.sha256(response.read()).hexdigest() not in allowed_css or response.headers.get('Cache-Control')!='no-store':
                raise RuntimeError('Random scene CSS verification failed')
        urls['NATURE_SCENE']=scene_url
    css = (args.theme / 'theme.css').read_text()
    for key, url in urls.items():
        css = css.replace('__ASSET_' + key + '__', url)
    if '__ASSET_' in css:
        raise RuntimeError('Unresolved CSS asset reference')
    # DRF trims the textarea value; normalize before comparing for idempotence.
    css = css.strip()
    protected_json(args.root / 'quiet-mono-media.json', urls)
    rendered = args.root / 'quiet-mono-rendered.css'
    rendered.write_text(css)
    rendered.chmod(0o600)
    if args.action == 'prepare':
        print('Prepared/verified', len(urls), 'same-origin immutable static assets; no brand/flow changes')
        return

    rows, current = exact_brand()
    base = current or next(row for row in rows if row['default'])
    flow = api('GET', 'flows/instances/?slug=default-authentication-flow')['results']
    if len(flow) != 1:
        raise RuntimeError('Expected one default authentication flow')
    flow = flow[0]
    ident = api('GET', 'stages/identification/?name=default-authentication-identification')['results']
    password = api('GET', 'stages/password/?name=default-authentication-password')['results']
    if len(ident) != 1 or len(password) != 1:
        raise RuntimeError('Expected reviewed native identification/password stages')
    ident, password = ident[0], password[0]
    if ident.get('password_stage') not in (None, password['pk']):
        raise RuntimeError('Unexpected inline password stage; refusing to replace it')
    # Do not silently overwrite an unrelated existing custom theme.
    if current and current.get('branding_custom_css') and 'Quiet Mono v5' not in current['branding_custom_css']:
        raise RuntimeError('Unmanaged domain CSS found; manual review required')
    payload = {key: base[key] for key in FIELDS if key in base}
    attributes = dict(base.get('attributes') or {})
    attributes['settings'] = {**attributes.get('settings', {}), 'locale': 'en', 'theme': 'light'}
    payload.update(domain=HOST, default=False, branding_title='Socrat',
        branding_logo=urls['MASK'], branding_favicon=urls['FAVICON'],
        branding_default_flow_background=urls['CLEAR_BACKGROUND'] if 'NATURE_RANDOM_DESKTOP' in urls else urls['LAKE'], branding_custom_css=css,
        attributes=attributes)
    if current and all(current.get(key) == value for key, value in payload.items()) and flow['title'] == 'Sign in' and ident.get('password_stage') == password['pk'] and password.get('allow_show_password'):
        print('Quiet Mono Brand already reconciled; no changes')
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup_path = args.root / 'theme-backups' / ('before-quiet-mono-' + stamp + '.json')
    protected_json(backup_path, {'brand_before': current, 'default_brand': base, 'flow_before': flow, 'identification_before': ident, 'password_before': password})
    created = None
    try:
        if current:
            created = api('PATCH', 'core/brands/' + current['brand_uuid'] + '/', payload)
        else:
            created = api('POST', 'core/brands/', payload)
        api('PATCH', 'flows/instances/' + flow['slug'] + '/', {'title': 'Sign in'})
        api('PATCH', 'stages/identification/' + ident['pk'] + '/', {'password_stage': password['pk'], 'user_fields': ident['user_fields']})
        api('PATCH', 'stages/password/' + password['pk'] + '/', {'allow_show_password': True})
        protected_json(journal_path, {'brand_uuid': created['brand_uuid'], 'backup': str(backup_path),
            'css_sha256': hashlib.sha256(css.encode()).hexdigest(), 'version': '2026.8.5'})
    except Exception:
        if created:
            if current:
                api('PATCH', 'core/brands/' + created['brand_uuid'] + '/',
                    {key: current[key] for key in FIELDS if key in current})
            else:
                api('DELETE', 'core/brands/' + created['brand_uuid'] + '/')
        api('PATCH', 'flows/instances/' + flow['slug'] + '/', {'title': flow['title']})
        api('PATCH', 'stages/identification/' + ident['pk'] + '/', {'password_stage': ident.get('password_stage'), 'user_fields': ident['user_fields']})
        api('PATCH', 'stages/password/' + password['pk'] + '/', {'allow_show_password': password.get('allow_show_password', False)})
        raise
    print('Applied domain Brand, title and native combined identification/password form; protected rollback saved')


if __name__ == '__main__':
    main()
