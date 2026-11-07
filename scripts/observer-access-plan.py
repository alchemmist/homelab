#!/usr/bin/env python3
"""Pure, fail-closed one-time native bootstrap planner. No credentials or writes.

Snapshot input is private. Output contains only minimal configuration operations;
no client secrets, passwords, OAuth tokens, per-user grants, or group polling.
The profile's ongoing authorization is performed by native OIDC/Rancher RBAC.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READ = {'get', 'list', 'watch'}
OWNER = 'observer-v1'


def require(value, message):
    if not value:
        raise ValueError(message)


def exact(rows, key, value):
    result = [row for row in rows if row.get(key) == value]
    require(len(result) == 1, 'Missing/ambiguous reviewed object: ' + value)
    return result[0]


def kpatch(obj, path, changes):
    meta = obj['metadata']
    patch = [{'op': 'test', 'path': '/metadata/uid', 'value': meta['uid']},
             {'op': 'test', 'path': '/metadata/resourceVersion', 'value': meta['resourceVersion']}]
    for field, value in changes.items():
        patch.append({'op': 'add', 'path': '/' + field, 'value': value})
    return {'system': 'kubernetes', 'method': 'PATCH', 'path': path, 'body': patch}


def build(state, policy):
    require(isinstance(state, dict) and isinstance(policy, dict), 'Observer state and policy must be objects')
    try:
        return _build(state, policy)
    except (KeyError, TypeError, AttributeError, IndexError):
        raise ValueError('Malformed observer state/policy: missing field or incorrect nested structure') from None


def _build(state, policy):
    require(policy['version'] == 1 and policy['group'] == 'homelab-observer', 'Unreviewed profile')
    require(set(policy['nativeAdmission']) == {'grafana', 'wiki', 'rancher', 'argocd'}
            and len(policy['nativeAdmission']) == 4 and policy['harbor']['enabled'] is False, 'Unreviewed app scope')
    require(policy['harbor']['projects'] == ['homelab', 'library', 'spi-triage'], 'Unreviewed project scope')
    rancher = policy['rancher']
    require(rancher['groupPrincipal'] == 'genericoidc_group://homelab-observer'
            and rancher['cluster'] == 'local'
            and rancher['globalRole'] == 'homelab-observer-login'
            and rancher['clusterRole'] == 'homelab-observer-cluster', 'Unreviewed principal/cluster')
    require(rancher['humanSessionMinutes'] == 60 and rancher['denyExtCredentialMinting'] is True
            and rancher['legacySelfCredentialsReadOnly'] is True, 'Unreviewed session/token policy')
    group = exact(state['groups'], 'name', policy['group'])
    require(group.get('is_superuser') is False and group.get('roles') == [] and group.get('parents') == [],
            'Observer must not carry IdP administration or inherited grants')
    supported_targets = {app['pk'] for app in state['apps'] if app['slug'] in policy['nativeAdmission']}
    harbor_app = exact(state['apps'], 'slug', 'harbor')
    gated_targets = {harbor_app['pk']}
    unexpected = [b for b in state['bindings'] if b.get('group') == group['pk']
                  and b.get('enabled') and b.get('target') not in supported_targets | gated_targets]
    require(not unexpected, 'Observer still admits unsupported apps; migrate legacy admission before rollout')
    # Source RBAC must be activated/reviewed before enabling group admission.
    login = state['rancherLoginRole']
    require(login['metadata']['name'] == rancher['globalRole']
            and login['metadata'].get('labels', {}).get('homelab.alchemmist.xyz/identity-profile') == OWNER,
            'Native login role has not been deployed under reviewed ownership')
    require(login.get('newUserDefault') is True, 'Safe new-user default role is not active')
    for rule in login.get('rules', []):
        require(not set(rule.get('resources', [])) & {'tokens', 'kubeconfigs', 'clusters', '*'},
                'Login role can mint credentials or create infrastructure')
    role = state['rancherClusterRole']
    require(role['metadata']['name'] == rancher['clusterRole']
            and role['metadata'].get('labels', {}).get('homelab.alchemmist.xyz/identity-profile') == OWNER,
            'Native cluster role ownership mismatch')
    require(role.get('context') == 'cluster' and not role.get('roleTemplateNames')
            and not role.get('administrative') and not role.get('external'), 'Unexpected role inheritance')
    for rule in role['rules']:
        require(set(rule.get('verbs', [])) <= READ and '*' not in rule.get('resources', [])
                and '*' not in rule.get('apiGroups', []), 'Cluster role is not a bounded reader')
        require(not set(rule.get('resources', [])) & {
            'secrets', 'configmaps', 'pods/log', 'pods/exec', 'pods/attach', 'pods/portforward',
            'nodes/proxy', 'services/proxy', 'serviceaccounts/token', 'tokens', 'kubeconfigs',
            'clusterroles', 'clusterrolebindings', 'roles', 'rolebindings'}, 'Sensitive reader grant')
    binding = state['rancherGroupBinding']
    require(binding.get('groupPrincipalName') == rancher['groupPrincipal']
            and binding.get('roleTemplateName') == rancher['clusterRole']
            and binding.get('clusterName') == 'local'
            and binding['metadata'].get('namespace') == 'local'
            and not any(binding.get(x) for x in ['userName', 'userPrincipalName', 'groupName']),
            'Group binding must not be per-user or point at another cluster')
    definitions = json.loads((ROOT / 'deploy/platform/rancher/public-entry/files/observer-rbac.json').read_text())
    for actual, desired in zip([login, role, binding], definitions):
        for key, value in desired.items():
            if key == 'metadata':
                require(all((all(actual['metadata'].get('labels', {}).get(a) == b for a, b in v.items())
                             if k == 'labels' else actual['metadata'].get(k) == v) for k, v in value.items()),
                        'Native object ownership drift')
            else:
                require(actual.get(key) == value, 'Native object specification drift: ' + key)
    require(not any(login.get(k) for k in ['inheritedClusterRoles', 'inheritedFleetWorkspacePermissions',
                                         'inheritedNamespacedRules', 'namespacedRules']), 'Hidden login inheritance')
    require(not role.get('externalRules'), 'Unexpected external role rules')
    ops = []
    # Default User grants cluster creation; User Base grants long-lived token
    # minting. Neither is a safe fallback for a new strict UI observer.
    for default in state['globalRoles']:
        if default.get('newUserDefault') and default['metadata']['name'] != rancher['globalRole']:
            require(default['metadata']['name'] in {'user', 'user-base'}, 'Unknown default grant; review')
            ops.append(kpatch(default, '/apis/management.cattle.io/v3/globalroles/' + default['metadata']['name'],
                              {'newUserDefault': False}))
    setting = state['rancherSessionSetting']
    require(setting['metadata']['name'] == 'auth-user-session-ttl-minutes', 'Unexpected setting')
    if (setting.get('value') or setting.get('default')) != '60':
        ops.append(kpatch(setting, '/apis/management.cattle.io/v3/settings/auth-user-session-ttl-minutes', {'value': '60'}))
    # Harbor's default can allow every logged-in user to create projects.
    # Restrict creation before enabling observer admission. Existing project
    # push/pull robot memberships and owner OIDC admin group are untouched.
    harbor = policy['harbor']
    require(harbor['groupType'] == 3 and harbor['roleId'] == 3
            and harbor['projectCreationRestriction'] == 'adminonly', 'Not a reviewed Harbor Guest policy')
    require(state['harbor']['oidcGroupsClaim'] == 'groups'
            and state['harbor']['oidcAdminGroup'] == 'homelab-owner', 'Harbor OIDC mapping drift')
    if state['harbor']['projectCreationRestriction'] != 'adminonly':
        ops.append({'system': 'harbor', 'method': 'PUT', 'path': '/api/v2.0/configurations',
                    'body': {'project_creation_restriction': 'adminonly'}})
    native_groups = state['harbor']['groups']
    require(len(native_groups) <= 1 and all(g.get('group_name') == policy['group']
            and g.get('group_type') == 3 for g in native_groups), 'Ambiguous/non-OIDC Harbor group')
    for project in harbor['projects']:
        require(project in state['harbor']['projects'], 'Missing reviewed Harbor project')
        members = state['harbor']['projects'][project]
        existing = [m for m in members if m.get('entity_type') == 'g' and m.get('entity_name') == policy['group']]
        require(len(existing) <= 1, 'Duplicate Harbor group membership')
        if existing:
            require(existing[0]['role_id'] == 3, 'Existing group is not Guest; no silent downgrade/adoption')
            require(len(native_groups) == 1 and existing[0].get('entity_id') == native_groups[0]['id'],
                    'Harbor membership does not reference the reviewed OIDC group')
            require(type(existing[0].get('id')) is int and existing[0]['id'] > 0, 'Missing owned Harbor member identity')
            ops.append({'system': 'harbor', 'method': 'DELETE',
                        'path': '/api/v2.0/projects/' + project + '/members/' + str(existing[0]['id']), 'body': None})
    auth = state['rancherAuth']
    require(auth.get('enabled') is True and auth.get('accessMode') == 'restricted'
            and auth.get('groupsClaim') == 'groups', 'Rancher authentication is not the reviewed restricted provider')
    allowed = auth['allowedPrincipalIds']
    require(isinstance(allowed, list) and len(set(allowed)) == len(allowed), 'Ambiguous admission')
    if rancher['groupPrincipal'] not in allowed:
        ops.append(kpatch(auth, '/apis/management.cattle.io/v3/authconfigs/genericoidc',
                          {'allowedPrincipalIds': allowed + [rancher['groupPrincipal']]}))
    # Close only this group's Harbor admission; Guest CLI cache is not revocable.
    for gated in [b for b in state['bindings'] if b.get('target') == harbor_app['pk'] and b.get('group') == group['pk']]:
        require(gated.get('enabled') is True and gated.get('negate') is False
                and not gated.get('policy') and not gated.get('user') and not gated.get('failure_result'),
                'Complex gated Harbor admission; stop for review')
        require(isinstance(gated.get('pk'), str) and gated['pk'], 'Missing Harbor binding identity')
        ops.append({'system': 'authentik', 'method': 'DELETE', 'path': 'policies/bindings/' + gated['pk'] + '/', 'body': None})
    # Admission is last. All existing groups/clients/native identities stay put.
    for slug in policy['nativeAdmission']:
        app = exact(state['apps'], 'slug', slug)
        require(app.get('provider') is not None and app['policy_engine_mode'] == 'any', 'Unexpected native app')
        bindings = [b for b in state['bindings'] if b.get('target') == app['pk']]
        require(all({'enabled', 'negate', 'policy', 'user', 'failure_result', 'group'} <= set(b)
                    and b.get('enabled') is True and b.get('negate') is False and not b.get('policy')
                    and not b.get('user') and not b.get('failure_result') and b.get('group') for b in bindings),
                'Complex app admission; do not broaden it implicitly')
        own = [b for b in bindings if b.get('group') == group['pk']]
        require(len(own) <= 1, 'Duplicate observer admission')
        if not own:
            ops.append({'system': 'authentik', 'method': 'POST', 'path': 'policies/bindings/',
                        'body': {'target': app['pk'], 'group': group['pk'], 'enabled': True, 'negate': False,
                                 'failure_result': False, 'order': 100, 'user': None, 'policy': None}})
    return ops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--policy', type=Path, default=ROOT / 'deploy/identity/observer/profile.json')
    args = parser.parse_args()
    require(not args.snapshot.is_symlink() and args.snapshot.is_file() and args.snapshot.stat().st_mode & 0o077 == 0,
            'Snapshot must be a private regular file')
    state = json.loads(args.snapshot.read_text())
    policy = json.loads(args.policy.read_text())
    operations = build(state, policy)
    digest = hashlib.sha256(json.dumps({'snapshot': state, 'policy': policy, 'operations': operations},
                                     sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    print(json.dumps({'applied': False, 'plan_hash': digest, 'operations': operations}, indent=2))


if __name__ == '__main__':
    main()
