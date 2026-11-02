#!/usr/bin/env python3
"""Bounded empty-group IAM preparation. Default plan/check use GET only.

Not a foundation reconciler, lifecycle controller, or native integration rollout.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

BASE = 'https://auth.socrat.alchemmist.xyz/api/v3/'
MARKER = {'homelab_app_iam': 1}
ALLOWLIST = {
    'grafana': ('viewer', 'editor'), 'harbor': ('user',),
    'rancher': ('user',), 'open-webui': ('user',), 'n8n': ('user',),
    'wiki': ('reader', 'editor'), 'lms': ('student',),
}
PINNED = {'alchemmist': '9e33877a-3eaa-4541-98eb-8cdc10088ef6',
          'tim': '0d2c194a-dee7-4226-b599-0a44ce2f2b76'}
# Detailed OAuth/proxy and MFA serializers supplement polymorphic inventories.
# No device secrets, recovery codes, tokens, sessions or native service APIs read.
COLLECTIONS = (
    'core/groups/', 'core/users/', 'providers/all/', 'providers/oauth2/',
    'providers/proxy/', 'core/applications/', 'policies/bindings/',
    'stages/all/', 'stages/authenticator/validate/', 'stages/authenticator/totp/',
    'flows/instances/', 'flows/bindings/', 'propertymappings/all/',
    'outposts/instances/',
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def tool_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def private(path, directory=False):
    s = path.lstat()
    require(not stat.S_ISLNK(s.st_mode) and
            (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)) and
            s.st_uid == os.getuid() and not s.st_mode & 0o077,
            'Private owned directory/file required')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise RuntimeError('API redirect refused')


def api_for(root):
    private(root, directory=True)
    path = root / 'credentials.json'
    private(path)
    credentials = json.loads(path.read_text())
    # Retired bootstrap spelling remains compatible; conflicting aliases fail.
    tokens = [credentials[k] for k in ('AUTHENTIK_API_TOKEN', 'AUTHENTIK_BOOTSTRAP_TOKEN')
              if k in credentials]
    require(tokens and all(isinstance(t, str) and t and t == tokens[0] for t in tokens),
            'Private API token unavailable or ambiguous')
    token = tokens[0]
    opener = urllib.request.build_opener(NoRedirect())  # default verified HTTPS context

    def api(method, endpoint, payload=None):
        require(method in ('GET', 'POST') and endpoint.split('?')[0] in COLLECTIONS and
                (method == 'GET' or endpoint in ('core/groups/', 'policies/bindings/')),
                'Request outside preparation boundary')
        request = urllib.request.Request(BASE + endpoint, method=method,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
            data=encoded(payload) if payload is not None else None)
        try:
            with opener.open(request, timeout=45) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            # Close without reading/logging: unclosed HTTPError ResourceWarnings can
            # echo an untrusted server reason phrase during garbage collection.
            error.close()
            raise RuntimeError('API request failed; outcome may be uncertain') from None
        except (urllib.error.URLError, OSError, ValueError):
            # Never include response bodies, URLs, credentials or server errors.
            raise RuntimeError('API request failed; outcome may be uncertain') from None
    return api


def rows(api, path):
    result = []
    for page in range(1, 1001):
        query = {'page_size': 100, 'page': page}
        if path == 'core/applications/':
            query['superuser_full_list'] = 'true'
        data = api('GET', path + '?' + urllib.parse.urlencode(query))
        require(isinstance(data, dict) and type(data.get('results')) is list and
                type(data.get('pagination')) is dict and 'next' in data['pagination'],
                'Incomplete paginated inventory')
        result.extend(data['results'])
        nxt = data['pagination']['next']
        require(nxt is None or (type(nxt) is int and nxt in (0, page + 1)),
                'Unexpected pagination cursor')
        if nxt is None or nxt == 0:
            return result
    raise RuntimeError('Pagination limit exceeded')


def unique(items, key):
    result = {}
    for item in items:
        require(isinstance(item, dict) and key in item and
                (type(item[key]) in (str, int) if key == 'pk' else type(item[key]) is str) and
                item[key] not in result, 'Missing/ambiguous inventory identity')
        result[item[key]] = item
    return result


def snapshot(api):
    state = {}
    for path in COLLECTIONS:
        items = rows(api, path)
        unique(items, 'pk')
        state[path] = sorted(items, key=encoded)
    return state


def hashes(state):
    return {path: digest(items) for path, items in state.items()}


def empty_group(group):
    require(group.get('is_superuser') is False and
            all(type(group.get(k)) is list and group[k] == []
                for k in ('parents', 'children', 'users', 'roles')) and
            group.get('parent') is None and type(group.get('attributes')) is dict and
            group['attributes'] == MARKER and
            type(group['attributes'].get('homelab_app_iam')) is int,
            'App group is not explicitly marked, empty and relation-free')


def group_payload(name):
    return {'name': name, 'is_superuser': False, 'parents': [], 'children': [],
            'users': [], 'roles': [], 'attributes': dict(MARKER)}


def evidence_input(path):
    if path is None:
        return None
    private(path)
    evidence = json.loads(path.read_text())
    required = {'version', 'reviewed_commit', 'reviewed_tool_sha256', 'backup_sha256',
                'restore_test_sha256', 'recovery_owner', 'change_window', 'writers_paused'}
    require(set(evidence) == required and evidence['version'] == 1 and
            evidence['writers_paused'] is True and
            re.fullmatch(r'[0-9a-f]{40}', evidence['reviewed_commit']) is not None and
            all(re.fullmatch(r'[0-9a-f]{64}', evidence[k]) is not None
                for k in ('reviewed_tool_sha256', 'backup_sha256', 'restore_test_sha256')) and
            all(isinstance(evidence[k], str) and evidence[k].strip()
                for k in ('recovery_owner', 'change_window')) and
            evidence['reviewed_tool_sha256'] == tool_hash(),
            'Reviewed backup/recovery evidence invalid')
    return evidence


def build_plan(api, services, reviewed, stage='groups-only', evidence=None):
    require(stage in ('groups-only', 'groups+empty-bindings'), 'Unknown stage')
    actual = {slug: set(s.get('appRoles', {})) for slug, s in services.items()
              if s.get('appRoles')}
    require(actual == {k: set(v) for k, v in ALLOWLIST.items()}, 'Catalog allowlist changed')
    require(all(reviewed.get(n, {}).get('idpUserUuid') == u for n, u in PINNED.items()),
            'Reviewed owner/Tim UUID mismatch')
    state = snapshot(api)
    groups = unique(state['core/groups/'], 'name')
    users = unique(state['core/users/'], 'username')
    unique(state['core/users/'], 'uuid')
    apps = unique(state['core/applications/'], 'slug')
    providers = unique(state['providers/all/'], 'pk')
    names = {f'app-{s}-{r}' for s, roles in ALLOWLIST.items() for r in roles}
    require(not any(n.startswith('app-') and n not in names for n in groups),
            'Unexpected app group; separate review required')
    for name in names & groups.keys():
        empty_group(groups[name])
    app_pks = {g['pk'] for n, g in groups.items() if n in names}
    for user in users.values():
        require(type(user.get('groups')) is list and not app_pks.intersection(user['groups']),
                'App membership present or user inventory incomplete')
    for name, uuid in PINNED.items():
        user = users.get(name)
        require(user is not None and user.get('uuid') == uuid and
                user.get('is_active') is True and user.get('type') == 'internal',
                'Pinned active owner/Tim missing or changed')
        require(all(g in groups and groups[g]['pk'] in user['groups']
                    for g in reviewed[name]['groups']), 'Pinned legacy membership missing')
    require(users['tim'].get('is_superuser') is False and
            groups['homelab-owner']['pk'] not in users['tim']['groups'],
            'Tim privilege drift')
    operations = []
    missing = names - groups.keys()
    # Never invent future PK pairs. Stage B is planned only AFTER Stage A GET verification.
    require(stage == 'groups-only' or not missing,
            'Run groups-only first; binding pairs require existing group PKs')
    for name in sorted(missing):
        operations.append({'method': 'POST', 'path': 'core/groups/', 'payload': group_payload(name)})
    bindings = state['policies/bindings/']
    for slug in sorted(ALLOWLIST):
        app = apps.get(slug)
        require(app is not None and app.get('policy_engine_mode') == 'any' and
                app.get('provider') in providers, 'Application/provider missing or not ANY')
        legacy = services[slug].get('groups')
        require(type(legacy) is list and legacy and len(set(legacy)) == len(legacy) and
                all(n in groups and not n.startswith('app-') for n in legacy),
                'Missing/invalid legacy admission groups')
        allowed_names = legacy + [f'app-{slug}-{r}' for r in ALLOWLIST[slug]]
        allowed = {groups[n]['pk'] for n in allowed_names if n in groups}
        seen = set()
        for binding in bindings:
            if binding.get('target') != app['pk']:
                continue
            group = binding.get('group')
            require(group in allowed and group not in seen and
                    binding.get('user', 'missing') is None and
                    binding.get('policy', 'missing') is None and
                    binding.get('enabled') is True and binding.get('negate') is False and
                    binding.get('failure_result') is False,
                    'Unexpected/duplicate/incomplete application binding')
            seen.add(group)
        require({groups[n]['pk'] for n in legacy} <= seen, 'Legacy binding missing')
        if stage == 'groups+empty-bindings':
            for name in sorted(set(allowed_names) - set(legacy)):
                if groups[name]['pk'] not in seen:
                    operations.append({'method': 'POST', 'path': 'policies/bindings/',
                        'payload': {'target': app['pk'], 'group': groups[name]['pk'],
                                    'enabled': True, 'negate': False, 'failure_result': False,
                                    'user': None, 'policy': None, 'order': 100}})
    require(len(operations) <= 9, 'Preparation request bound exceeded')
    context = {'version': 1, 'tool_sha256': tool_hash(), 'services': services,
               'reviewed': reviewed, 'stage': stage, 'evidence': evidence,
               'snapshot_hashes': hashes(state), 'operations': operations}
    return {'sha256': digest(context), 'tool_sha256': context['tool_sha256'],
            'stage': stage, 'snapshot_hashes': context['snapshot_hashes'],
            'evidence_sha256': digest(evidence) if evidence is not None else None,
            'operations': operations}, state


@contextmanager
def locked(root):
    private(root, directory=True)
    fd = os.open(root / '.app-iam-prepare.lock',
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        private(root / '.app-iam-prepare.lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another preparation invocation holds the lock') from None
        yield
    finally:
        os.close(fd)  # never unlink a lock inode another invocation may hold


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    fd, tmp = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(encoded(value)); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def apply_plan(api, root, services, reviewed, stage, evidence, approval):
    """Caller holds exclusive local lock. No resume, rollback or automatic adoption."""
    require(evidence is not None, 'Apply requires reviewed backup/recovery evidence')
    plan, state = build_plan(api, services, reviewed, stage, evidence)
    require(approval == plan['sha256'], 'Approval mismatch or baseline drift; review fresh plan')
    journals = root / 'app-iam-prepare-journal'
    if not journals.exists():
        journals.mkdir(mode=0o700)
        sync_directory(root)
    private(journals, directory=True)
    for previous in journals.iterdir():
        private(previous, directory=True)
        status = previous / 'run.json'
        if status.exists():
            private(status)
        require(status.exists() and json.loads(status.read_text()).get('status') == 'complete',
                'Unresolved prior journal; manual inventory/review required')
    run = journals / str(uuid4())
    run.mkdir(mode=0o700)
    sync_directory(journals)
    record = {'sha256': plan['sha256'], 'status': 'in-progress'}
    atomic_json(run / 'run.json', record)
    try:
        # Second complete fresh snapshot immediately before first write.
        require(hashes(snapshot(api)) == hashes(state), 'Baseline drift before apply')
        for index, operation in enumerate(plan['operations'], 1):
            entry = {'operation': operation, 'status': 'pending'}
            path = run / f'{index:02d}.json'
            atomic_json(path, entry)  # durable intent BEFORE sending POST
            created = api(operation['method'], operation['path'], operation['payload'])
            require(isinstance(created, dict) and 'pk' in created and
                    all(created.get(k) == v for k, v in operation['payload'].items()),
                    'Create response mismatch; stop and inventory')
            if operation['path'] == 'core/groups/':
                empty_group(created)
            else:
                require(created.get('user', 'missing') is None and
                        created.get('policy', 'missing') is None,
                        'Create binding response incomplete')
            require(created['pk'] not in unique(state[operation['path']], 'pk'),
                    'Create returned pre-existing object; stop')
            entry.update(status='created', pk=created['pk'])
            atomic_json(path, entry)
            state[operation['path']].append(created)
            state[operation['path']].sort(key=encoded)
            fresh = snapshot(api)
            require(hashes(fresh) == hashes(state),
                    'Unexpected post-create drift; stop and inventory')
            state = fresh
            entry.update(status='verified', snapshot_hashes=hashes(state))
            atomic_json(path, entry)
        final, _ = build_plan(api, services, reviewed, stage, evidence)
        require(not final['operations'] and final['snapshot_hashes'] == hashes(state),
                'Post-apply verification failed')
        record.update(status='complete', snapshot_hashes=hashes(state))
        atomic_json(run / 'run.json', record)
    except BaseException:
        record['status'] = 'stopped-uncertain'
        atomic_json(run / 'run.json', record)
        raise
    return len(plan['operations'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('action', choices=('plan', 'check', 'apply'), default='plan', nargs='?')
    parser.add_argument('--stage', choices=('groups-only', 'groups+empty-bindings'), default='groups-only')
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--approve-sha256')
    args = parser.parse_args()
    with locked(args.root):
        api = api_for(args.root)
        services = json.loads((args.root / 'services.json').read_text())
        reviewed = json.loads((args.root / 'account-mappings.json').read_text())
        evidence = evidence_input(args.evidence)
        if args.action == 'apply':
            count = apply_plan(api, args.root, services, reviewed, args.stage, evidence, args.approve_sha256)
            print(f'PASS: {count} verified create requests; no assignments or native rollout')
            return 0
        plan, _ = build_plan(api, services, reviewed, args.stage, evidence)
        print(json.dumps(plan, indent=2))  # only request allowlist + hashes, never API responses
        return int(args.action == 'check' and bool(plan['operations']))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, KeyError, ValueError, TypeError, AttributeError):
        # Sanitized fixed text also covers malformed/untrusted API/input values.
        raise SystemExit('Preparation stopped: private input/API/schema/drift/approval or journal failure; inspect locally, never replay configure.py') from None
