#!/usr/bin/env python3
"""Secret-free Kubernetes machine-peer staging, NOT the legacy Docker router.

All Deployments are deliberately replicas=0. No API/apply/enrollment operation.
Real JWT groups, fresh live gates and single-use runtime keys are prerequisites
for a separately reviewed activation. No imported client/server routes.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
NS = 'netbird-host-peers'
HOSTS = ('socrat-0', 'socrat-2')
IFACE = 'nb-host'
SOURCES = ('netbird-pilot-grafana', 'netbird-pilot-ssh-socrat-2')
DESTINATIONS = ('netbird-machine-grafana', 'netbird-machine-ssh-socrat-2')
GRAFANA = 'grafana.socrat.alchemmist.xyz'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def image(name):
    lock = json.loads((ROOT / 'deploy/netbird/images.lock.json').read_text())['images'][name]
    if name == 'edge_forwarder':
        return lock['reference']
    require(lock['repository'] == 'netbirdio/netbird' and lock['tag'] == '0.82.0', 'client version drift')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', lock['digest']), 'client digest missing')
    return lock['repository'] + ':' + lock['tag'] + '@' + lock['digest']


def preflight(policies, groups, peers, mem_available_kib):
    """Validate live reads; never synthesise JWT-issued groups using the API."""
    require(policies == [], 'policies must be empty before first machine enrollment')
    require(peers == [], 'expected no preexisting peers; inspect before any replay')
    result = []
    for name in SOURCES:
        matches = [g for g in groups if g['name'] == name]
        require(len(matches) == 1 and matches[0].get('issued') == 'jwt', 'real JWT source group required: ' + name)
        require(not matches[0].get('peers') and not matches[0].get('resources'), 'source group has unexpected members')
        result.append(matches[0]['id'])
    require(len(set(result)) == 2, 'source groups collide')
    # Conservative full budget, even though Grafana on the VPS is optional.
    require(mem_available_kib >= (256 + 96 + 32 + 32 + 1) * 1024,
            'VPS reserve <256Mi after peer96 + frontend32 + STUN32 + tmp1Mi budget')
    return result


def setup_key_body(host):
    require(host in HOSTS, 'unapproved host')
    return {'name': 'machine-' + host, 'type': 'one-off', 'expires_in': 600,
            'usage_limit': 1, 'auto_groups': [], 'ephemeral': False,
            'allow_extra_dns_labels': False}


def policies(source_ids, destination_ids):
    require(len(source_ids) == len(destination_ids) == 2 and
            len(set(source_ids + destination_ids)) == 4 and all(source_ids + destination_ids), 'four dedicated group IDs required')
    return [{'name': name, 'description': 'Machine own-overlay INPUT, no routed networks', 'enabled': True,
             'rules': [{'name': name, 'enabled': True, 'action': 'accept', 'protocol': 'tcp',
                        'bidirectional': False, 'sources': [src], 'destinations': [dst], 'ports': [str(port)]}]}
            for name, src, dst, port in zip(('pilot-grafana', 'pilot-ssh-socrat-2'), source_ids, destination_ids, (8443, 2222))]


def peer(host, *, admin_mesh=False):
    reviewed = ('socrat-0', 'socrat-1', 'socrat-2', 'socrat-3') if admin_mesh else HOSTS
    require(host in reviewed, 'unapproved host')
    name = 'machine-' + host
    labels = {'app': name}
    env = {'NB_MANAGEMENT_URL': 'https://netbird.socrat.alchemmist.xyz',
           'NB_HOSTNAME': name, 'NB_INTERFACE_NAME': IFACE, 'NB_WIREGUARD_PORT': '51871',
           'NB_DISABLE_CLIENT_ROUTES': 'true', 'NB_DISABLE_SERVER_ROUTES': 'true',
           'NB_DISABLE_DNS': 'true', 'NB_DISABLE_IPV6': 'true',
           'NB_DISABLE_FIREWALL': 'false', 'NB_ALLOW_SERVER_SSH': 'false',
           'NB_CONFIG': '/etc/netbird/config.json', 'NB_LOG_LEVEL': 'warn',
           'NB_LOG_FILE': '/dev/null', 'NB_ENABLE_CAPTURE': 'false'}
    return [
        {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name, 'namespace': NS},
         'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'local-path',
                  'resources': {'requests': {'storage': '64Mi'}}}},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': name, 'namespace': NS},
         'spec': {'replicas': 0, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': labels},
                  'template': {'metadata': {'labels': labels}, 'spec': {
                      'hostNetwork': True, 'dnsPolicy': 'ClusterFirstWithHostNet',
                      'automountServiceAccountToken': False,
                      'nodeSelector': {'kubernetes.io/hostname': host},
                      'containers': [{'name': 'peer', 'image': image('client'),
                          'env': [{'name': k, 'value': v} for k, v in env.items()] + [
                              {'name': 'NB_SETUP_KEY', 'valueFrom': {'secretKeyRef': {'name': name + '-enrollment', 'key': 'setup-key'}}}],
                          'resources': {'requests': {'memory': '32Mi', 'cpu': '10m'},
                                        'limits': {'memory': '96Mi', 'cpu': '500m'}},
                          'securityContext': {'runAsUser': 0, 'allowPrivilegeEscalation': False,
                              'capabilities': {'drop': ['ALL'], 'add': ['NET_ADMIN', 'NET_RAW', 'BPF']},
                              'seccompProfile': {'type': 'RuntimeDefault'}},
                          'volumeMounts': [{'name': 'state', 'mountPath': '/etc/netbird'},
                                           {'name': 'tun', 'mountPath': '/dev/net/tun'}]}],
                      'volumes': [{'name': 'state', 'persistentVolumeClaim': {'claimName': name}},
                                  {'name': 'tun', 'hostPath': {'path': '/dev/net/tun', 'type': 'CharDevice'}}]
                  }}}}]


def overlay_ip(value):
    ip = ipaddress.ip_address(value)
    require(ip.version == 4 and ip in ipaddress.ip_network('100.64.0.0/10'), 'actual CGNAT peer IPv4 required')
    return str(ip)


def frontend_config(address):
    address = overlay_ip(address)
    return {'static.yaml': yaml.safe_dump({
                'entryPoints': {'grafana': {'address': address + ':8443'}},
                'providers': {'file': {'filename': '/etc/traefik/dynamic.yaml'}},
                'log': {'level': 'WARN'}}, sort_keys=False),
            'dynamic.yaml': yaml.safe_dump({
                'http': {'routers': {'grafana': {'rule': 'Host(`' + GRAFANA + '`)',
                    'entryPoints': ['grafana'], 'service': 'grafana', 'tls': {'options': 'strict'},
                    'middlewares': ['fixed-upstream-host']}},
                    'middlewares': {'fixed-upstream-host': {'headers': {'customRequestHeaders': {'Host': GRAFANA}}}},
                    'services': {'grafana': {'loadBalancer': {'passHostHeader': True,
                        'serversTransport': 'verified', 'servers': [{'url': 'https://10.250.0.3:443'}]}}},
                    'serversTransports': {'verified': {'serverName': GRAFANA, 'insecureSkipVerify': False}}},
                'tls': {'options': {'strict': {'sniStrict': True, 'minVersion': 'VersionTLS12'}},
                    'certificates': [{'certFile': '/tls/tls.crt', 'keyFile': '/tls/tls.key'}]}}, sort_keys=False)}


def frontend(host, address):
    require(host in HOSTS, 'unapproved host')
    name = 'grafana-' + host
    labels = {'app': name}
    return [
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name, 'namespace': NS},
         'data': frontend_config(address)},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': name, 'namespace': NS},
         'spec': {'replicas': 0, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': labels},
                  'template': {'metadata': {'labels': labels}, 'spec': {
                      'hostNetwork': True, 'automountServiceAccountToken': False,
                      'nodeSelector': {'kubernetes.io/hostname': host},
                      'containers': [{'name': 'frontend', 'image': image('edge_forwarder'),
                          'args': ['--configFile=/etc/traefik/static.yaml'],
                          'resources': {'requests': {'memory': '16Mi', 'cpu': '5m'},
                                        'limits': {'memory': '32Mi', 'cpu': '100m'}},
                          'securityContext': {'runAsUser': 65532, 'runAsNonRoot': True,
                              'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                              'capabilities': {'drop': ['ALL']}},
                          'volumeMounts': [{'name': 'config', 'mountPath': '/etc/traefik', 'readOnly': True},
                                           {'name': 'tls', 'mountPath': '/tls', 'readOnly': True}]}],
                      'volumes': [{'name': 'config', 'configMap': {'name': name}},
                                  {'name': 'tls', 'secret': {'secretName': 'grafana-frontend-tls'}}]
                  }}}}]


def frontend_guard():
    # A DROP only; no global SSH accept/drop, forward hooks, NAT or sysctl changes.
    return ('table inet netbird_peer_frontend {\n'
            ' chain input { type filter hook input priority -10; policy accept;\n'
            '  iifname != "nb-host" tcp dport 8443 counter drop\n'
            ' }\n}\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frontend-host', choices=HOSTS)
    p.add_argument('--overlay-ip')
    p.add_argument('--frontend-guard', action='store_true')
    a = p.parse_args()
    if a.frontend_guard:
        print(frontend_guard(), end='')
        return
    require(bool(a.frontend_host) == bool(a.overlay_ip), 'frontend host and actual overlay IP are required together')
    docs = [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS}}]
    for host in HOSTS:
        docs.extend(peer(host))
    if a.frontend_host:
        docs.extend(frontend(a.frontend_host, a.overlay_ip))
    print(yaml.safe_dump_all(docs, sort_keys=False), end='')


if __name__ == '__main__':
    main()
