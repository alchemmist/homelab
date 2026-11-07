"""Pure retention guard; only the reviewed bootstrap may open group admission."""
PRINCIPAL = 'genericoidc_group://homelab-observer'


def retain_observer(original, allowed, roles, ttl):
    result = list(allowed)
    if PRINCIPAL not in original.get('allowedPrincipalIds', []):
        return result
    safe = next((r for r in roles if r['metadata']['name'] == 'homelab-observer-login'), None)
    ready = bool(safe and safe.get('newUserDefault') is True
                 and safe['metadata'].get('labels', {}).get('homelab.alchemmist.xyz/identity-profile') == 'observer-v1'
                 and all(not r.get('newUserDefault') or r['metadata']['name'] == 'homelab-observer-login' for r in roles)
                 and (ttl.get('value') or ttl.get('default')) == '60')
    if not ready:
        raise RuntimeError('Observer defaults drifted; do not silently rewrite active group admission')
    if PRINCIPAL not in result:
        result.append(PRINCIPAL)
    return result


def authconfig_patch(original, settings):
    """Do not overwrite another writer's admission/configuration changes."""
    return [{'op': 'test', 'path': '/metadata/uid', 'value': original['metadata']['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': original['metadata']['resourceVersion']}] + [
                {'op': 'add', 'path': '/' + key.replace('~', '~0').replace('/', '~1'), 'value': value}
                for key, value in settings.items()]
