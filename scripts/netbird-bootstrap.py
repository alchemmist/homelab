#!/usr/bin/env python3
"""Claim a NetBird v0.82.0 instance only through a loopback port-forward.

The public forwarder denies /api/setup. This client refuses the public FQDN,
never sends create_pat, and never prints the password or a personal access token.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def setup_body(email, password, name):
    require(isinstance(email, str) and 3 <= len(email) <= 254 and email.count('@') == 1, 'email invalid')
    require(isinstance(password, str) and len(password) >= 8, 'password too short')
    require(isinstance(name, str) and name.strip() and len(name) <= 128, 'name required')
    # SetupRequest required fields only. create_pat is omitted, so no setup PAT is requested.
    return {'email': email, 'password': password, 'name': name.strip()}


def assert_loopback(origin):
    require(isinstance(origin, str) and '://' in origin, 'origin required')
    scheme, rest = origin.split('://', 1)
    require(scheme == 'http', 'bootstrap requires a local http port-forward')
    require('@' not in rest, 'credentials in the URL are forbidden')
    hostport = rest.split('/', 1)[0]
    host = hostport
    if host.startswith('['):
        require(host.endswith(']') or ']:' in host, 'invalid IPv6 origin')
        host = host[1:].split(']', 1)[0]
    elif ':' in hostport:
        host = hostport.rsplit(':', 1)[0]
    require(host in {'127.0.0.1', 'localhost', '::1'}, 'bootstrap target must be loopback')
    require(rest.endswith(hostport) or rest.endswith(hostport + '/'), 'do not pass an API path')
    lowered = origin.lower()
    require('netbird.' not in lowered and 'alchemmist' not in lowered, 'public FQDN is not a bootstrap target')


def redact(payload):
    require(isinstance(payload, dict) and 'user_id' in payload and 'email' in payload, 'unexpected setup response')
    redacted = {'user_id': payload['user_id'], 'email': payload['email']}
    if payload.get('personal_access_token'):
        redacted['personal_access_token_redacted'] = True
    return redacted


def claim(origin, email, password, name, opener):
    assert_loopback(origin)
    base = origin.rstrip('/')
    status = opener(base + '/api/instance', None)
    require(isinstance(status, dict) and status.get('setup_required') is True,
            'instance is not waiting for setup')
    body = setup_body(email, password, name)
    require('create_pat' not in body and 'password' in body, 'setup body drifted from SetupRequest')
    result = opener(base + '/api/setup', body)
    return redact(result)


def env_credentials():
    return (os.environ.get('NB_BOOTSTRAP_EMAIL', ''),
            os.environ.get('NB_BOOTSTRAP_PASSWORD', ''),
            os.environ.get('NB_BOOTSTRAP_NAME', ''))


def urllib_opener(url, body):
    data = None if body is None else json.dumps(body).encode()
    method = 'GET' if body is None else 'POST'
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={'Accept': 'application/json', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError('setup endpoint rejected the request') from exc


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--origin', required=True, help='Loopback origin from kubectl port-forward, not the public FQDN')
    a = p.parse_args()
    email, password, name = env_credentials()
    result = claim(a.origin, email, password, name, urllib_opener)
    print(json.dumps(result, indent=2))
    for secret in (password, os.environ.get('NB_BOOTSTRAP_PASSWORD', '')):
        require(not secret or secret not in json.dumps(result), 'bootstrap output included a credential')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print('BLOCKED: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        sys.exit(2)
