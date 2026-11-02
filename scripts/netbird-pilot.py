#!/usr/bin/env python3
"""Offline-only NetBird pilot compiler. Never applies resources or calls production APIs."""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'deploy/netbird/images.lock.json'
REVIEWS = {'dns_tls_public_before_vpn', 'stun_udp_3478_to_nodeport',
           'overlay_overlap_checked', 'dedicated_router_hosts_confirmed',
           'both_routers_reach_every_resource', 'endpoint_ip_port_scope_reviewed'}
NS = 'netbird-pilot'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def hostname(value):
    return (text(value) and len(value) < 254 and '.' in value and
            all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x)
                for x in value.split('.')) and not value.endswith(('.example', '.invalid')))


def identifier(value):
    return text(value) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', value)


def validate(c):
    expected = {'schema_version', 'management_fqdn', 'management_node', 'tls_secret_name', 'ingress_class',
                'stun_node_port', 'storage_class', 'overlay_cidr', 'authentik_issuer',
                'oidc_client_id', 'login_group', 'routing_peers', 'resources', 'review'}
    require(isinstance(c, dict) and set(c) == expected, 'unexpected/missing input keys')
    require(type(c['schema_version']) is int and c['schema_version'] == 1, 'unsupported schema_version')
    require(hostname(c['management_fqdn']), 'management_fqdn: approved public FQDN required')
    for key in ['management_node', 'tls_secret_name', 'storage_class', 'ingress_class']:
        require(identifier(c[key]), key + ': reviewed Kubernetes identifier required')
    require(type(c['stun_node_port']) is int and 30000 <= c['stun_node_port'] <= 32767,
            'stun_node_port: reviewed free UDP NodePort required')
    overlay = ipaddress.ip_network(c['overlay_cidr'], strict=True)
    require(overlay.version == 4 and 16 <= overlay.prefixlen <= 24,
            'overlay_cidr: dedicated IPv4 /16 through /24 required')
    for protected in ['10.250.0.0/24', '10.42.0.0/16', '10.43.0.0/16',
                      '192.168.0.0/24', '172.17.0.0/16', '172.18.0.0/16']:
        require(not overlay.overlaps(ipaddress.ip_network(protected)), 'overlay overlaps existing transport')
    require(any(overlay.subnet_of(ipaddress.ip_network(x)) for x in
                ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10']),
            'overlay must use RFC1918 or CGNAT address space')
    issuer = c['authentik_issuer']
    require(text(issuer) and re.fullmatch(r'https://[a-z0-9.-]+/application/o/[a-z0-9-]+/', issuer),
            'authentik_issuer: exact HTTPS application issuer required')
    require(text(c['oidc_client_id']), 'oidc_client_id required (not a secret)')
    require(text(c['login_group']) and c['login_group'] != 'All', 'dedicated login_group required')
    require(isinstance(c['review'], dict) and set(c['review']) == REVIEWS and
            all(v is True for v in c['review'].values()), 'all review gates must explicitly be true')
    peers = c['routing_peers']
    require(isinstance(peers, list) and len(peers) == 2, 'exactly TWO dedicated routing peers required')
    for p in peers:
        require(set(p) == {'name', 'host', 'failure_domain', 'metric'}, 'routing peer keys invalid')
        require(identifier(p['name']) and hostname(p['host']), 'routing peer name/host required')
        require(not re.search(r'socrat-[0-3]|^[0-3]\.socrat', p['host']) and
                p['host'] != c['management_node'], 'routing peers must NOT be existing K3s/mesh nodes')
        require(text(p['failure_domain']), 'routing peer failure_domain required')
        require(type(p['metric']) is int and 1 <= p['metric'] <= 9999, 'router metric invalid')
    for key in ['name', 'host', 'failure_domain', 'metric']:
        require(len({p[key] for p in peers}) == 2, 'routing peers need distinct ' + key)
    resources = c['resources']
    require(isinstance(resources, list) and bool(resources), 'explicit resource allowlist required')
    require(len({r['name'] for r in resources}) == len(resources), 'duplicate resource names')
    seen = set()
    for r in resources:
        require(set(r) == {'name', 'kind', 'address', 'ports', 'source_group', 'dns_name'},
                'resource keys invalid')
        require(identifier(r['name']), 'resource name invalid')
        ip = ipaddress.ip_network(r['address'], strict=True)
        require(ip.version == 4 and ip.prefixlen == 32 and
                any(ip.subnet_of(ipaddress.ip_network(x)) for x in
                    ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']) and
                not ip.overlaps(overlay), 'resources must be RFC1918 IPv4 /32 hosts outside overlay')
        require(not any(ip.overlaps(ipaddress.ip_network(x)) for x in ['10.42.0.0/16', '10.43.0.0/16']),
                'pod/service CIDRs are not pilot endpoints')
        require(r['kind'] in ['web', 'ssh'], 'only web/ssh resources allowed')
        require(isinstance(r['ports'], list) and r['ports'] and
                all(type(p) is int and 1 <= p <= 65535 for p in r['ports']) and
                len(set(r['ports'])) == len(r['ports']), 'explicit unique TCP ports required')
        require(r['kind'] != 'ssh' or r['ports'] == [2222], 'existing SSH must stay TCP 2222')
        require(r['kind'] != 'web' or r['ports'] == [443], 'web pilot permits TLS TCP 443 only')
        require(text(r['source_group']) and r['source_group'] != 'All', 'dedicated source_group required')
        require(r['kind'] != 'web' or hostname(r['dns_name']), 'web dns_name required for TLS/SNI')
        require(r['kind'] != 'ssh' or r['dns_name'] is None or hostname(r['dns_name']), 'SSH DNS invalid')
        require((r['address'], tuple(r['ports'])) not in seen, 'duplicate IP/port resource')
        seen.add((r['address'], tuple(r['ports'])))
    return c


def image(name):
    item = json.loads(LOCK.read_text())['images'][name]
    return item['repository'] + ':' + item['tag'] + '@' + item['digest']


def server_config(c, secrets):
    return {'server': {
        'listenAddress': ':80', 'exposedAddress': 'https://' + c['management_fqdn'] + ':443',
        'stunPorts': [3478], 'metricsPort': 9090, 'healthcheckAddress': ':9000',
        'logLevel': 'info', 'logFile': 'console', 'dataDir': '/var/lib/netbird',
        'disableAnonymousMetrics': True, 'disableGeoliteUpdate': True,
        'authSecret': secrets['NB_RELAY_SECRET'],
        'auth': {'issuer': 'https://' + c['management_fqdn'] + '/oauth2',
                 'signKeyRefreshEnabled': True,
                 'sessionCookieEncryptionKey': secrets['NB_COOKIE_KEY'],
                 'dashboardRedirectURIs': ['https://' + c['management_fqdn'] + x
                                          for x in ['/nb-auth', '/nb-silent-auth']],
                 'cliRedirectURIs': ['http://localhost:53000/']},
        'store': {'engine': 'sqlite', 'encryptionKey': secrets['NB_STORE_KEY']}}}


def account_settings(c):
    return {'network_range': c['overlay_cidr'], 'jwt_groups_enabled': True,
            'jwt_groups_claim_name': 'groups', 'jwt_allow_groups': [c['login_group']],
            'groups_propagation_enabled': True, 'peer_login_expiration_enabled': True,
            'peer_login_expiration': 3600, 'peer_inactivity_expiration_enabled': True,
            'peer_inactivity_expiration': 3600, 'regular_users_view_blocked': True,
            'peer_expose_enabled': False, 'peer_expose_groups': [],
            'auto_update_version': 'disabled', 'auto_update_always': False,
            'routing_peer_dns_resolution_enabled': False, 'ipv6_enabled_groups': []}


def manifests(c):
    def obj(kind, name, api='v1', **fields):
        return {'apiVersion': api, 'kind': kind,
                'metadata': {'name': name, 'namespace': NS}, **fields}
    result = [obj('Namespace', NS)]
    result[0]['metadata'].pop('namespace')
    result.append(obj('PersistentVolumeClaim', 'server-data', spec={
        'storageClassName': c['storage_class'], 'accessModes': ['ReadWriteOnce'],
        'resources': {'requests': {'storage': '5Gi'}}}))
    base = 'https://' + c['management_fqdn']
    env = {'NETBIRD_MGMT_API_ENDPOINT': base, 'NETBIRD_MGMT_GRPC_API_ENDPOINT': base,
           'AUTH_AUDIENCE': 'netbird-dashboard', 'AUTH_CLIENT_ID': 'netbird-dashboard',
           'AUTH_AUTHORITY': base + '/oauth2', 'USE_AUTH0': 'false',
           'AUTH_SUPPORTED_SCOPES': 'openid profile email groups', 'AUTH_REDIRECT_URI': '/nb-auth',
           'AUTH_SILENT_REDIRECT_URI': '/nb-silent-auth', 'LETSENCRYPT_DOMAIN': 'none'}
    for name in ['server', 'dashboard']:
        container = {'name': name, 'image': image(name), 'imagePullPolicy': 'IfNotPresent',
                     'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'},
                                   'limits': {'cpu': '1', 'memory': '768Mi'}},
                     'ports': [{'name': 'http', 'containerPort': 80}]}
        pod = {'automountServiceAccountToken': False,
               'nodeSelector': {'kubernetes.io/hostname': c['management_node']},
               'containers': [container]}
        if name == 'server':
            container.update(args=['--config', '/etc/netbird/config.yaml'],
                             volumeMounts=[{'name': 'config', 'mountPath': '/etc/netbird', 'readOnly': True},
                                           {'name': 'data', 'mountPath': '/var/lib/netbird'}],
                             readinessProbe={'httpGet': {'path': '/oauth2/.well-known/openid-configuration', 'port': 80}, 'initialDelaySeconds': 10},
                             livenessProbe={'tcpSocket': {'port': 80}, 'initialDelaySeconds': 60})
            container['ports'] += [{'name': 'stun', 'containerPort': 3478, 'protocol': 'UDP'},
                                   {'name': 'health', 'containerPort': 9000}]
            pod['volumes'] = [{'name': 'config', 'secret': {'secretName': 'netbird-runtime', 'defaultMode': 0o400}},
                              {'name': 'data', 'persistentVolumeClaim': {'claimName': 'server-data'}}]
        else:
            container['env'] = [{'name': k, 'value': v} for k, v in env.items()]
            container['readinessProbe'] = {'httpGet': {'path': '/', 'port': 80}}
        result.append(obj('Deployment', name, 'apps/v1', spec={
            'replicas': 1, 'strategy': {'type': 'Recreate'},
            'selector': {'matchLabels': {'app': 'netbird-' + name}},
            'template': {'metadata': {'labels': {'app': 'netbird-' + name}}, 'spec': pod}}))
        result.append(obj('Service', name, spec={'selector': {'app': 'netbird-' + name},
                                               'ports': [{'name': 'http', 'port': 80, 'targetPort': 'http'}]}))
    result.append(obj('Service', 'stun', spec={
        'type': 'NodePort', 'externalTrafficPolicy': 'Local', 'selector': {'app': 'netbird-server'},
        'ports': [{'name': 'stun', 'port': 3478, 'targetPort': 'stun',
                   'protocol': 'UDP', 'nodePort': c['stun_node_port']}]}))
    host = 'Host(`' + c['management_fqdn'] + '`)'
    routes = []
    for paths, name, scheme in [(['/signalexchange.SignalExchange/', '/management.ManagementService/'], 'server', 'h2c'),
                                (['/api/', '/oauth2/', '/relay', '/ws-proxy/'], 'server', 'http')]:
        routes.append({'kind': 'Rule', 'match': host + ' && (' + ' || '.join(
            'PathPrefix(`' + p + '`)' for p in paths) + ')', 'priority': 100,
                       'services': [{'name': name, 'port': 80, 'scheme': scheme}]})
    routes.append({'kind': 'Rule', 'match': host, 'priority': 1,
                   'services': [{'name': 'dashboard', 'port': 80}]})
    result.append(obj('IngressRoute', 'netbird', 'traefik.io/v1alpha1', spec={
        'entryPoints': ['websecure'], 'routes': routes, 'tls': {'secretName': c['tls_secret_name']}}))
    result[-1]['metadata']['annotations'] = {'kubernetes.io/ingress.class': c['ingress_class']}
    return result


def router_compose(c, peer):
    return {'services': {'routing-peer': {
        'image': image('client'), 'restart': 'unless-stopped',
        'network_mode': 'host', 'cap_add': ['NET_ADMIN', 'SYS_ADMIN', 'SYS_RESOURCE'],
        'devices': ['/dev/net/tun:/dev/net/tun'],
        'environment': {'NB_MANAGEMENT_URL': 'https://' + c['management_fqdn'],
                        'NB_SETUP_KEY_FILE': '/run/secrets/setup_key', 'NB_HOSTNAME': peer['name'],
                        'NB_INTERFACE_NAME': 'nb-pilot0',
                        'NB_WIREGUARD_PORT': '51840', 'NB_DISABLE_DNS': 'true',
                        'NB_ALLOW_SERVER_SSH': 'false', 'NB_LOG_FILE': 'console'},
        'volumes': ['netbird-state:/etc/netbird'], 'secrets': ['setup_key'],
        'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '2'}}}},
        'volumes': {'netbird-state': {}},
        'secrets': {'setup_key': {'file': '${NETBIRD_SETUP_KEY_FILE:?protected runtime setup-key file required}'}}}


def access_requests(c, bindings, snapshot):
    """Compile only against reviewed IDs from an EMPTY, dedicated pilot account/network."""
    require(set(snapshot) == {'policies', 'routes', 'groups', 'peers', 'networks'}, 'snapshot keys invalid')
    require(snapshot['policies'] == [] and snapshot['routes'] == [],
            'remove DEFAULT/other policies and legacy routes BEFORE enrolling pilot devices')
    require(set(bindings) == {'network_id', 'source_groups', 'resource_groups', 'peer_ids'},
            'binding keys invalid')
    groups = sorted({r['source_group'] for r in c['resources']})
    require(set(bindings['source_groups']) == set(groups), 'exact source group bindings required')
    require(set(bindings['resource_groups']) == {r['name'] for r in c['resources']},
            'exact resource group bindings required')
    require(set(bindings['peer_ids']) == {p['name'] for p in c['routing_peers']},
            'exact two peer ID bindings required')
    values = [bindings['network_id']] + [v for key in ['source_groups', 'resource_groups', 'peer_ids']
                                        for v in bindings[key].values()]
    require(all(text(v) and re.fullmatch(r'[a-z0-9]{10,64}', v) for v in values),
            'real API IDs required, no placeholders')
    require(len(values) == len(set(values)), 'IDs must be distinct; never bind All/shared resource groups')
    require(len(snapshot['networks']) == 1, 'dedicated empty pilot Network required')
    pilot = snapshot['networks'][0]
    require(pilot.get('id') == bindings['network_id'] and pilot.get('name') == 'netbird-pilot' and
            all(type(pilot.get(k)) is list and pilot[k] == [] for k in ['routers', 'resources', 'policies']) and
            type(pilot.get('routing_peers_count')) is int and pilot['routing_peers_count'] == 0,
            'complete current API response for an empty pilot Network required; no replay/partial deployment')
    for key, names in [('source_groups', groups), ('resource_groups', [r['name'] for r in c['resources']])]:
        for name in names:
            found = [g for g in snapshot['groups'] if g['id'] == bindings[key][name]]
            expected = name if key == 'source_groups' else 'pilot-resource-' + name
            require(len(found) == 1 and found[0]['name'] == expected and expected != 'All' and
                    len([g for g in snapshot['groups'] if g.get('name') == expected]) == 1,
                    'group ID/name mismatch; All/shared groups forbidden')
            if key == 'source_groups':
                require(found[0].get('issued') == 'jwt', 'source groups must originate from JWT, not matching API names')
            if key == 'resource_groups':
                require(found[0].get('issued') == 'api' and
                        all(type(found[0].get(k)) is list and found[0][k] == [] for k in ['peers', 'resources']),
                        'destination groups must be complete, API-issued empty dedicated resource groups')
    for peer in c['routing_peers']:
        found = [p for p in snapshot['peers'] if p['id'] == bindings['peer_ids'][peer['name']]]
        require(len(found) == 1 and found[0]['name'] == peer['name'], 'routing peer ID/name mismatch')
    network = '/api/networks/' + bindings['network_id']
    requests = []
    for p in c['routing_peers']:
        requests.append({'method': 'POST', 'path': network + '/routers', 'body': {
            'peer': bindings['peer_ids'][p['name']], 'metric': p['metric'],
            'masquerade': True, 'enabled': True}})
    for r in c['resources']:
        group = bindings['resource_groups'][r['name']]
        requests.append({'method': 'POST', 'path': network + '/resources', 'body': {
            'name': r['name'], 'address': r['address'], 'enabled': True, 'groups': [group]}})
        requests.append({'method': 'POST', 'path': '/api/policies', 'body': {
            'name': 'pilot-' + r['name'], 'enabled': True, 'rules': [{
                'name': r['name'], 'enabled': True, 'action': 'accept', 'bidirectional': False,
                'protocol': 'tcp', 'ports': [str(p) for p in r['ports']],
                'sources': [bindings['source_groups'][r['source_group']]], 'destinations': [group]}]}})
    return requests


def dump(path, value, yaml_format=False, private=False):
    # No overwrites or symlink following; runtime output must be on a protected local tmpfs.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(path, flags, 0o600 if private else 0o644)
    with os.fdopen(fd, 'w') as f:
        f.write(yaml.safe_dump(value, sort_keys=False) if yaml_format else json.dumps(value, indent=2) + '\n')


def render(c, out):
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    with (out / 'management.yaml').open('w') as f:
        yaml.safe_dump_all(manifests(c), f, sort_keys=False)
    dump(out / 'account-settings.merge.json', account_settings(c))
    dump(out / 'access-intent.json', {'network': 'netbird-pilot', 'routers': c['routing_peers'],
                                    'resources': c['resources']})
    dump(out / 'oidc-public.json', {'type': 'oidc', 'name': 'Authentik pilot',
                                   'issuer': c['authentik_issuer'], 'client_id': c['oidc_client_id']})
    for p in c['routing_peers']:
        dump(out / (p['name'] + '.compose.yaml'), router_compose(c, p), yaml_format=True)


def verify_images():
    for name, item in json.loads(LOCK.read_text())['images'].items():
        token_url = 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:' + item['repository'] + ':pull'
        with urllib.request.urlopen(token_url, timeout=25) as r:
            token = json.load(r)['token']
        url = 'https://registry-1.docker.io/v2/' + item['repository'] + '/manifests/' + item['tag']
        req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read()
            require(r.headers['Docker-Content-Digest'] == item['digest'] == 'sha256:' + hashlib.sha256(raw).hexdigest(),
                    name + ': registry tag/index no longer matches lock')
        entries = json.loads(raw)['manifests']
        for arch in ['amd64', 'arm64']:
            require(any(x['platform'] == {'os': 'linux', 'architecture': arch} and
                        x['digest'] == item['linux_' + arch] for x in entries), name + ': platform digest mismatch')
        print(name + ': verified registry index and Linux amd64/arm64 pins')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['validate', 'render', 'runtime-config', 'compile-access', 'verify-images'])
    p.add_argument('--inputs', type=Path, default=ROOT / 'deploy/netbird/pilot.inputs.json')
    p.add_argument('--out', type=Path)
    p.add_argument('--bindings', type=Path)
    p.add_argument('--snapshot', type=Path)
    a = p.parse_args()
    if a.command == 'verify-images':
        verify_images()
        return
    c = validate(json.loads(a.inputs.read_text()))
    if a.command == 'validate':
        print('Inputs valid; NOT evidence of deployment or acceptance')
        return
    require(a.out is not None, '--out required')
    require(not a.out.resolve().is_relative_to(ROOT), '--out must be outside the Git worktree (including runtime secrets)')
    if a.command == 'render':
        render(c, a.out)
    elif a.command == 'runtime-config':
        secrets = {key: os.environ.get(key, '') for key in ['NB_RELAY_SECRET', 'NB_COOKIE_KEY', 'NB_STORE_KEY']}
        require(all(text(v) and len(v) >= 32 for v in secrets.values()), 'runtime secrets missing or too short')
        for key in ['NB_COOKIE_KEY', 'NB_STORE_KEY']:
            try:
                decoded = base64.b64decode(secrets[key], validate=True)
            except ValueError:
                decoded = b''
            require(len(decoded) == 32, key + ': base64-encoded 32 random bytes required')
        require(len(set(secrets.values())) == 3, 'runtime secrets must be distinct')
        dump(a.out, server_config(c, secrets), yaml_format=True, private=True)
    else:
        require(a.bindings is not None and a.snapshot is not None,
                '--bindings and --snapshot required; compiler never calls production APIs')
        dump(a.out, access_requests(c, json.loads(a.bindings.read_text()), json.loads(a.snapshot.read_text())))
    print('Local files written; nothing applied')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # Never include input values, server responses or environment secrets in errors.
        print('BLOCKED: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        sys.exit(2)
