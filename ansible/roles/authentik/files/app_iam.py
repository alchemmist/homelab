"""Shared additive application admission contract; no human grants or role elevation."""
from urllib.parse import urlencode

LEGACY_GROUPS = ['homelab-owner', 'homelab-platform-operator',
                 'homelab-project-maintainer', 'homelab-observer',
                 'homelab-machine-owner', 'lms-students']


def app_groups(services):
    return {f'app-{slug}-{role}': settings
            for slug, service in services.items()
            for role, settings in service.get('appRoles', {}).items()}


def admission_groups(slug, service):
    # Legacy membership remains valid; this is admission, NOT native RBAC.
    return service.get('groups', ['homelab-owner']) + [
        f'app-{slug}-{role}' for role in service.get('appRoles', {})]


def rows(api, path):
    """Follow Authentik page numbers, never arbitrary next URLs with credentials."""
    result = []; page = 1
    while True:
        data = api('GET', path + ('&' if '?' in path else '?') +
                   urlencode({'page_size': 100, 'page': page}))
        result.extend(data['results'])
        if not data.get('pagination', {}).get('next'):
            return result
        page += 1
        if page > 1000:
            raise RuntimeError('Pagination limit exceeded')


GROUP_MARKER = {'homelab_app_iam': 1}


def validate_group(group):
    # Authentik 2026.8.5 uses plural parents (M2M), not legacy parent.
    # Missing/null/reduced responses are not evidence of absence of privilege.
    if (group.get('is_superuser') is not False or
            type(group.get('parents')) is not list or group['parents'] != [] or
            type(group.get('roles')) is not list or group['roles'] != [] or
            group.get('parent') is not None):
        raise RuntimeError('App group must be non-superuser without inheritance/RBAC: ' + group['name'])
    if group.get('attributes') != GROUP_MARKER:
        raise RuntimeError('Refusing adoption of unmarked app group: ' + group['name'])


def validate_bindings(bindings, allowed):
    """Do not silently reset UI policy, or accept bypasses in ANY mode."""
    seen = set()
    for binding in bindings:
        group = binding.get('group')
        if (group not in allowed or group in seen or binding.get('user') or
                binding.get('policy') or not binding.get('enabled', True) or
                binding.get('negate', False) or binding.get('failure_result', False)):
            raise RuntimeError('Application binding drift; review UI policy before reconciliation')
        seen.add(group)
    return seen
