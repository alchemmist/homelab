#!/usr/bin/env python3
"""Optional Authentik public keys -> reviewed Ansible assignments. GET/plan only by default.

Never executes Ansible or writes to Authentik/hosts. Export contains public keys only.
Bindings are an append-only Git ledger, NOT username/email/group matching.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
BINDINGS = ROOT / 'deploy/identity/ssh-bindings.json'
POLICY = ROOT / 'deploy/identity/ssh-assignments.json'
EXCLUDED = {'root', 'alchemmist', 'ghactions'}
KEY_TYPES = ('ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256',
             'sk-ssh-ed25519@openssh.com', 'sk-ecdsa-sha2-nistp256@openssh.com')


class Refused(ValueError):
    """Safe error, deliberately excludes raw API responses/attributes/credentials."""


def require(ok, message):
    if not ok:
        raise Refused(message)


def fields(obj, expected):
    require(isinstance(obj, dict) and set(obj) == set(expected), 'Unexpected document fields')


def canonical_uuid(value):
    try:
        require(isinstance(value, str) and str(uuid.UUID(value)) == value, 'Canonical UUID required')
        require(uuid.UUID(value).int != 0, 'Nonzero UUID required')
    except (ValueError, AttributeError):
        raise Refused('Canonical UUID required') from None
    return value


def read_json(path):
    # Do not include decoder errors: they can contain supplied private material.
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON field')
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(), object_pairs_hook=unique_pairs)
    except (OSError, ValueError):
        raise Refused('Cannot read valid JSON input') from None


def bindings_map(document):
    fields(document, ['version', 'bindings'])
    require(document['version'] == 1 and isinstance(document['bindings'], list), 'Invalid binding ledger')
    result = {}
    for entry in document['bindings']:
        fields(entry, ['uuid', 'name'])
        ident, name = canonical_uuid(entry['uuid']), entry['name']
        require(isinstance(name, str) and re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', name)
                and name not in EXCLUDED, 'Restricted Linux username required')
        require(ident not in result and name not in result.values(), 'Duplicate UUID or Linux username')
        result[ident] = name
    return result


def validate_history(current, histories):
    for old in histories:
        for ident, name in bindings_map(old).items():
            require(current.get(ident) == name, 'Immutable binding removed or changed; retain tombstones')


def binding_history():
    """Fail closed without full Git history. A binding is never reused, even after revoke."""
    def git(*args):
        try:
            return subprocess.run(['git', '-C', str(ROOT), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise Refused('Full Git checkout required for binding history') from None
    require(git('rev-parse', '--is-shallow-repository') == 'false', 'Shallow binding history refused')
    path = str(BINDINGS.relative_to(ROOT))
    revisions = git('log', '--full-history', '--format=%H', 'HEAD', '--', path).splitlines()
    result = []
    for revision in revisions:
        try:
            result.append(json.loads(git('show', revision + ':' + path)))
        except ValueError:
            raise Refused('Invalid committed binding history') from None
    return result


def host_list(value):
    require(isinstance(value, list) and all(isinstance(h, str) and
            re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,62}', h) for h in value), 'Explicit inventory hosts required')
    require(len(set(value)) == len(value), 'Duplicate host assignment')
    return value


def validate_policy(policy, bindings):
    fields(policy, ['version', 'public_key_attribute', 'assignments'])
    require(policy['version'] == 1, 'Unsupported policy version')
    require(isinstance(policy['public_key_attribute'], str) and
            re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', policy['public_key_attribute']), 'Invalid attribute name')
    require(isinstance(policy['assignments'], list), 'Assignment list required')
    seen = set()
    for row in policy['assignments']:
        fields(row, ['uuid', 'state', 'hosts', 'revoked_hosts'])
        ident = canonical_uuid(row['uuid'])
        require(ident in bindings and ident not in seen, 'Unbound or duplicate assignment UUID')
        seen.add(ident)
        require(row['state'] in ['present', 'disabled'], 'Explicit present/disabled state required')
        hosts, revoked = host_list(row['hosts']), host_list(row['revoked_hosts'])
        require(bool(hosts or revoked), 'Empty host scope refused')
        require(not set(hosts) & set(revoked), 'Active and revoked hosts overlap')
        require(row['state'] != 'present' or bool(hosts), 'Present assignment needs explicit hosts')
    return policy


def validate_transition(policy, histories):
    """Previously managed hosts must remain explicit, including disabled tombstones."""
    current = {r['uuid']: set(r['hosts'] + r['revoked_hosts']) for r in policy['assignments']}
    for old in histories:
        require(isinstance(old, dict) and isinstance(old.get('assignments'), list), 'Invalid policy history')
        for row in old['assignments']:
            require(set(row['hosts'] + row['revoked_hosts']) <= current.get(row['uuid'], set()),
                    'Removed host/assignment needs an explicit retained revocation tombstone')


def policy_history():
    # Same full-checkout trust boundary as bindings. Only this fixed path is read.
    path = str(POLICY.relative_to(ROOT))
    try:
        revisions = subprocess.run(['git', '-C', str(ROOT), 'log', '--full-history', '--format=%H', 'HEAD', '--', path],
                                   check=True, text=True, capture_output=True).stdout.splitlines()
        return [json.loads(subprocess.run(['git', '-C', str(ROOT), 'show', r + ':' + path],
                check=True, text=True, capture_output=True).stdout) for r in revisions]
    except (OSError, ValueError, subprocess.SubprocessError):
        raise Refused('Cannot verify assignment history') from None


def public_keys(value):
    require(isinstance(value, list) and 0 < len(value) <= 32, 'Active assignment needs a public key list')
    result, fingerprints = [], []
    for line in value:
        require(isinstance(line, str) and len(line) <= 16384 and
                not any(ord(c) < 32 or ord(c) == 127 for c in line), 'Invalid public key line')
        parts = line.split()
        require(len(parts) >= 2 and parts[0] in KEY_TYPES and
                re.fullmatch(r'[A-Za-z0-9+/]+={0,3}', parts[1]), 'Unsupported public key format')
        # Drop untrusted comments. No authorized_keys options, certificates or multiline input.
        key = parts[0] + ' ' + parts[1]
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='ascii') as f:
                f.write(key + '\n'); f.flush()
                parsed = subprocess.run(['ssh-keygen', '-l', '-E', 'sha256', '-f', f.name],
                                        capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            raise Refused('OpenSSH public key parser unavailable') from None
        match = re.fullmatch(r'\d+ (SHA256:[A-Za-z0-9+/]+) .+\n?', parsed.stdout)
        require(parsed.returncode == 0 and match is not None, 'OpenSSH rejected public key')
        fingerprint = match.group(1)
        require(fingerprint not in fingerprints, 'Duplicate public key')
        fingerprints.append(fingerprint); result.append(key)
    return result, fingerprints


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refused('Authentik redirect refused')


class Authentik:
    def __init__(self, url, token, ca_file=None):
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and
                not parsed.password and parsed.path in ['', '/'] and not parsed.query and not parsed.fragment,
                'HTTPS Authentik origin required')
        require(isinstance(token, str) and token and not any(ord(c) < 33 or ord(c) > 126 for c in token),
                'AUTHENTIK_SSH_TOKEN required')
        self.url, self.token = url.rstrip('/'), token
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=ca_file)))

    def user(self, ident):
        canonical_uuid(ident)
        query = urllib.parse.urlencode({'uuid': ident, 'page_size': 100})
        request = urllib.request.Request(self.url + '/api/v3/core/users/?' + query,
                                        headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'},
                                        method='GET')
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024, 'Authentik response too large')
            document = json.loads(raw)
        except (OSError, ValueError, urllib.error.URLError):
            raise Refused('Authentik read failed (check TLS, token, permissions, API schema)') from None
        require(isinstance(document, dict) and isinstance(document.get('results'), list), 'Invalid user API response')
        # A UUID lookup must be unique and complete. Never follow untrusted next URLs.
        pagination = document.get('pagination')
        require(isinstance(pagination, dict) and 'next' in pagination and pagination['next'] is None,
                'Incomplete UUID lookup refused')
        rows = document['results']
        require(len(rows) == 1 and isinstance(rows[0], dict) and rows[0].get('uuid') == ident,
                'UUID lookup missing, ambiguous or unsupported')
        return rows[0]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def build_plan(bindings, policy, get_user):
    validate_policy(policy, bindings)
    by_host, summary = {}, []
    for row in policy['assignments']:
        ident, state = row['uuid'], row['state']
        keys, fingerprints = [], []
        if state == 'present':
            user = get_user(ident)
            require(isinstance(user, dict) and user.get('uuid') == ident, 'Missing immutable user UUID')
            require(user.get('is_active') is True, 'IdP user inactive; review explicit disabled assignment')
            require(user.get('type') == 'internal', 'Only internal human users may be assigned')
            attributes = user.get('attributes')
            require(isinstance(attributes, dict), 'Missing user attributes')
            keys, fingerprints = public_keys(attributes.get(policy['public_key_attribute']))
        for host in row['hosts'] + row['revoked_hosts']:
            effective = 'disabled' if host in row['revoked_hosts'] else state
            by_host.setdefault(host, []).append({'name': bindings[ident], 'authentik_uuid': ident, 'state': effective,
                'hosts': [host], 'shell': '/bin/bash', 'sudo': False, 'groups': [],
                'authorized_keys': keys if effective == 'present' else [],
                'key_fingerprints': fingerprints if effective == 'present' else []})
        summary.append({'uuid': ident, 'name': bindings[ident], 'state': state,
                        'hosts': row['hosts'], 'revoked_hosts': row['revoked_hosts'],
                        'fingerprints': fingerprints})
    payload = {'version': 1, 'bindings_digest': digest(bindings), 'policy_digest': digest(policy),
               'required_hosts': sorted(by_host), 'by_host': by_host}
    return payload, summary


def export(path, payload, approval):
    require(bool(payload['required_hosts']), 'Empty integration cannot be exported')
    review = digest(payload)
    require(approval == review, 'Export requires --approve-plan with the current review SHA256')
    target = Path(path).resolve()
    require(not target.is_relative_to(ROOT), 'Export outside the repository for review')
    document = {'homelab_authentik_ssh_payload': payload, 'homelab_authentik_ssh_review_sha256': review}
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(document, f, indent=2); f.write('\n')
    except OSError:
        raise Refused('Export refused; use a new private output file') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authentik-url', help='HTTPS origin, no API path; token from AUTHENTIK_SSH_TOKEN')
    parser.add_argument('--ca-file', help='Optional trusted CA bundle; verification is always enabled')
    parser.add_argument('--snapshot', type=Path, help='Public-only API user list for OFFLINE PLAN ONLY')
    parser.add_argument('--export', type=Path, help='Explicit public-only Ansible extra-vars export; no host writes')
    parser.add_argument('--approve-plan', help='SHA256 printed by the reviewed plan')
    args = parser.parse_args(argv)
    try:
        bindings = bindings_map(read_json(BINDINGS))
        validate_history(bindings, binding_history())
        policy = validate_policy(read_json(POLICY), bindings)
        validate_transition(policy, policy_history())
        require(not (args.snapshot and args.export), 'Offline snapshot is plan-only')
        if args.snapshot:
            users = read_json(args.snapshot)
            require(isinstance(users, list), 'Snapshot must be a public-only API user list')
            def get_user(ident):
                rows = [u for u in users if isinstance(u, dict) and u.get('uuid') == ident]
                require(len(rows) == 1, 'Snapshot UUID missing or duplicated')
                return rows[0]
        elif any(r['state'] == 'present' for r in policy['assignments']):
            api = Authentik(args.authentik_url or '', os.environ.get('AUTHENTIK_SSH_TOKEN'), args.ca_file)
            get_user = api.user
        else:
            get_user = lambda ident: None  # Disabled assignments deliberately need no IdP availability.
        payload, summary = build_plan(bindings, policy, get_user)
        print(json.dumps({'mode': 'read-only-plan', 'assignments': summary,
                          'review_sha256': digest(payload), 'required_hosts': payload['required_hosts']}, indent=2))
        if args.export:
            export(args.export, payload, args.approve_plan)
            print('Public-only export created. No Authentik, SSH or Ansible writes performed.')
        return 0
    except (Refused, OSError, ValueError) as error:
        # Even low-level exceptions must not echo API bodies, tokens, paths or raw keys.
        print('REFUSED: ' + (str(error) if isinstance(error, Refused)
                              else 'Cannot read trusted input or TLS configuration'), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
