#!/usr/bin/env python3
"""Anonymous negative probes only, forced public entrances with ordinary TLS validation."""
import argparse
import ast
import concurrent.futures
import ipaddress
import json
from pathlib import Path
import subprocess
import urllib.parse


def addresses(explicit=None):
    if explicit:
        values = explicit
    else:
        # Reuse the existing migration-owned public address inventory.
        source = Path(__file__).with_name('check-public-ingress.py')
        tree = ast.parse(source.read_text())
        values = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'ADDRESSES' for t in n.targets))
    if len(values) != 2 or len(set(values)) != 2 or any(
            ipaddress.ip_address(v).version != 4 or not ipaddress.ip_address(v).is_global for v in values):
        raise ValueError('Exactly two distinct public IPv4 entrances required')
    return values

PROXY_HOSTS = ['search.socrat.alchemmist.xyz',
               'llm.socrat.alchemmist.xyz', 'litellm.socrat.alchemmist.xyz',
               '0.socrat.alchemmist.xyz','1.socrat.alchemmist.xyz','kuma.socrat.alchemmist.xyz']

def probe(case):
    host, ip, path, expected = case[:4]
    method = case[4] if len(case) > 4 else 'GET'
    auth = case[5] if len(case) > 5 else 'Bearer intentionally-invalid'
    args = ['curl', '-sS', '--max-time', '12', '--path-as-is', '--resolve', f'{host}:443:{ip}',
            '-H', 'X-authentik-username: admin', '-H', 'X-authentik-groups: homelab-owner',
            '-H', 'X-Forwarded-For: 10.250.0.4', '-H', 'X-Forwarded-Host: evil.invalid',
            '-H', 'X-Forwarded-Proto: http',
            '-D', '-', '-o', '/dev/null', f'https://{host}{path}']
    if auth:
        args[1:1] = ['--header','Authorization: '+auth]
    if method == 'POST':
        args[1:1] = ['--request', 'POST', '--header', 'Content-Type: application/json', '--data', '{}']
    p = subprocess.run(args, text=True, capture_output=True, timeout=15)
    statuses = [line.split()[1] for line in p.stdout.splitlines() if line.startswith('HTTP/')]
    status = int(statuses[-1]) if statuses else 0
    location = next((line.split(':', 1)[1].strip() for line in p.stdout.splitlines()
                     if line.lower().startswith('location:')), '')
    u = urllib.parse.urlsplit(location)
    good = p.returncode == 0 and status == expected
    if expected == 302:
        if host=='grafana.socrat.alchemmist.xyz':
            good &= u.scheme in ('','https') and u.hostname in (None,host) and u.path in ('/login','/login/generic_oauth')
        elif host=='status.alchemmist.xyz':
            good &= u.scheme=='https' and u.hostname=='kuma.socrat.alchemmist.xyz' and u.path==urllib.parse.urlsplit(path).path
        else:
            good &= u.scheme == 'https' and u.hostname == host and u.path == '/outpost.goauthentik.io/start'
    return {'host': host, 'entrance': ip, 'path': path, 'method': method, 'status': status,
            'tls_verified': p.returncode == 0, 'passed': bool(good)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', action='append', help='Repeat twice when running outside the repository')
    ips = addresses(parser.parse_args().address)
    cases = [(h, ip, path, 302) for h in PROXY_HOSTS for ip in ips
             for path in ['/', '/api/search', '/api/admin/settings', '//api/search', '/metrics']]
    cases += [('grafana.socrat.alchemmist.xyz',ip,path,code,method,auth) for ip in ips for path,code,method,auth in
              [('/',302,'GET',None),('/api/search',401,'GET',None),('/api/admin/settings',401,'GET',None),
               ('/metrics',404,'GET',None),('/debug/pprof/',404,'GET',None),('/login',403,'POST',None),
               ('/api/user',403,'GET','Basic aW52YWxpZDppbnZhbGlk')]]
    cases += [('rancher.socrat.alchemmist.xyz', ip, path, 401) for ip in ips for path in
              ['/v3/users', '/v3/clusters', '/v3/connect/register', '/v1/management.cattle.io.users']]
    cases += [('rancher.socrat.alchemmist.xyz', ip, path, 403, 'POST') for ip in ips for path in
              ['/v3-public/localProviders/local?action=login', '//v3-public/localProviders/local?action=login']]
    cases += [('grafana-mcp.socrat.alchemmist.xyz', ip, path, code) for ip in ips for path, code in
              [('/mcp', 401), ('/metrics', 404), ('/healthz', 404)]]
    cases += [(host,ip,path,302) for host in ['0.socrat.alchemmist.xyz','1.socrat.alchemmist.xyz'] for ip in ips for path in ['/sync/','/sync/rest/config','/sync/rest/noauth/health']]
    cases += [('kuma.socrat.alchemmist.xyz',ip,path,302) for ip in ips for path in ['/dashboard','/socket.io/?EIO=4&transport=polling','/api/entry-page']]
    cases += [('status.alchemmist.xyz',ip,path,code) for ip in ips for path,code in [('/status/socrat',200),('/api/status-page/socrat',200),('/api/status-page/heartbeat/socrat',200),('/socket.io/?EIO=4&transport=polling',404),('/socket.io/?EIO=4&transport=websocket',404),('/metrics',404),('/api/settings',404),('/api/push/intentionally-invalid?status=up',404),('/dashboard',302),('/settings',302),('/login',302),('/manage-status-page',302)]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(probe, cases))
    failed = [r for r in results if not r['passed']]
    print(json.dumps({'checks': len(results), 'passed': len(results)-len(failed), 'failures': failed}, indent=2))
    if failed:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
