#!/usr/bin/env python3
"""Inventory-driven existing-cluster NetBird onboarding. Plan by default; no deletes.

Run on the trusted K3s controller. Never log API bodies, credentials or subprocess
output. Persistent cluster/node/PVC/deployment/peer bindings prohibit replacement
or re-enrollment by friendly name. Uncertain writes stop for operator inspection.
"""
import argparse
import datetime as dt
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

NS = 'netbird-host-peers'
ADMIN = 'netbird-internal-admins'
DEST = 'netbird-node-agents'
NETWORK = 'wireguard-internal'
SERVICE = 'homelab-netbird-node-automation'
BASE = 'https://netbird.socrat.alchemmist.xyz/api/'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def validate_config(c):
    require(re.fullmatch(r'netbirdio/netbird:0\.82\.0@sha256:[a-f0-9]{64}', c['image']), 'pinned client required')
    require(isinstance(c['nodes'], dict) and c['nodes'], 'inventory nodes required')
    ips = []
    for name, value in c['nodes'].items():
        require(re.fullmatch(r'socrat-[0-9]+', name), 'invalid inventory node name')
        ip = ipaddress.ip_address(value)
        require(ip.version == 4 and ip in ipaddress.ip_network('10.250.0.0/24')
                and int(str(ip).split('.')[-1]) not in (0, 255), 'explicit WG host address required')
        ips.append(str(ip))
    require(len(ips) == len(set(ips)), 'duplicate WG addresses')
    require(isinstance(c.get('reserved_addresses'), list), 'reserved client address inventory required')
    reserved = {str(ipaddress.ip_address(v)) for v in c['reserved_addresses']}
    require(not set(ips) & reserved, 'node address collides with a human/device WG client')
    return c


def manifests(host, image, enrollment=False):
    require(re.fullmatch(r'socrat-[0-9]+', host), 'invalid node')
    name = 'machine-' + host
    labels = {'app': name}
    env = {'NB_MANAGEMENT_URL': BASE[:-5], 'NB_HOSTNAME': name,
           'NB_INTERFACE_NAME': 'nb-host', 'NB_WIREGUARD_PORT': '51871',
           'NB_DISABLE_CLIENT_ROUTES': 'true', 'NB_DISABLE_SERVER_ROUTES': 'false',
           'NB_DISABLE_DNS': 'true', 'NB_DISABLE_IPV6': 'true',
           'NB_DISABLE_FIREWALL': 'false', 'NB_ALLOW_SERVER_SSH': 'false',
           'NB_CONFIG': '/etc/netbird/config.json', 'NB_LOG_LEVEL': 'warn',
           'NB_LOG_FILE': '/dev/null', 'NB_ENABLE_CAPTURE': 'false'}
    container = {'name': 'peer', 'image': image,
        'env': [{'name': k, 'value': v} for k, v in env.items()],
        'resources': {'requests': {'memory': '32Mi', 'cpu': '10m'},
                      'limits': {'memory': '96Mi', 'cpu': '500m'}},
        'securityContext': {'runAsUser': 0, 'allowPrivilegeEscalation': False,
            'capabilities': {'drop': ['ALL'], 'add': ['NET_ADMIN', 'NET_RAW', 'BPF']},
            'seccompProfile': {'type': 'RuntimeDefault'}},
        'volumeMounts': [{'name': 'state', 'mountPath': '/etc/netbird'},
                        {'name': 'tun', 'mountPath': '/dev/net/tun'}]}
    if enrollment:
        container['env'].append({'name': 'NB_SETUP_KEY', 'valueFrom': {
            'secretKeyRef': {'name': name+'-enrollment', 'key': 'setup-key'}}})
    return [
        {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
         'metadata': {'name': name, 'namespace': NS},
         'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'local-path',
                  'resources': {'requests': {'storage': '64Mi'}}}},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment',
         'metadata': {'name': name, 'namespace': NS},
         'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'},
             'selector': {'matchLabels': labels}, 'template': {
                 'metadata': {'labels': labels}, 'spec': {
                     'hostNetwork': True, 'dnsPolicy': 'ClusterFirstWithHostNet',
                     'automountServiceAccountToken': False,
                     'nodeSelector': {'kubernetes.io/hostname': host},
                     'tolerations': [{'key': 'homelab.io/bootstrap', 'operator': 'Equal',
                                      'value': 'true', 'effect': 'NoSchedule'}],
                     'containers': [container], 'volumes': [
                         {'name': 'state', 'persistentVolumeClaim': {'claimName': name}},
                         {'name': 'tun', 'hostPath': {'path': '/dev/net/tun', 'type': 'CharDevice'}}]}}}}]


def policy_body(source, resource):
    return {'name': 'admin-wg-'+resource, 'enabled': True,
        'description': 'Inventory node /32; native SSH authentication still required',
        'rules': [{'name': 'admin-to-wg-node', 'enabled': True, 'action': 'accept',
                   'protocol': 'all', 'bidirectional': False, 'sources': [source],
                   'destinationResource': {'id': resource, 'type': 'host'}}]}


def member_ids(group):
    return {p['id'] if isinstance(p, dict) else p for p in (group.get('peers') or [])}


def unique(items, key, value):
    found = [v for v in items if v.get(key) == value]
    require(len(found) == 1, 'missing or ambiguous '+key)
    return found[0]


def policy_ok(p, admin, resource=None, group=None):
    rules = p.get('rules') or []
    if not p.get('enabled') or len(rules) != 1:
        return False
    r = rules[0]
    src = {v['id'] if isinstance(v, dict) else v for v in (r.get('sources') or [])}
    dst = {v['id'] if isinstance(v, dict) else v for v in (r.get('destinations') or [])}
    return (r.get('enabled') and r.get('action') == 'accept' and r.get('protocol') == 'all'
            and r.get('bidirectional') is False and not r.get('ports') and src == {admin}
            and (r.get('destinationResource') or {}).get('id') == resource
            and (resource is None or r['destinationResource'].get('type') == 'host')
            and dst == ({group} if group else set()))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


class Runtime:
    def __init__(self, folder, config, apply=False):
        self.folder, self.config, self.apply = folder, validate_config(config), apply
        self.k = ['env', 'K3S_CONFIG_FILE=/dev/null', 'kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml']
        require(folder.stat().st_uid == os.geteuid(), 'state directory owner mismatch')
        self.auth_path = folder/'credential.json'
        require(not self.auth_path.is_symlink(), 'credential symlink refused')
        self.auth = json.loads(self.auth_path.read_text())
        require(not self.auth_path.stat().st_mode & 0o077, 'credential permissions')
        self.state_path = folder/'bindings.json'
        require(not self.state_path.is_symlink(), 'bindings symlink refused')
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {'nodes': {}}
        require(not self.state.get('pending'), 'uncertain previous write: inspect private bindings; no blind replay')
        self.changed = False

    def api(self, method, path, body=None):
        req = urllib.request.Request(BASE+path, method=method,
            headers={'Authorization': 'Token '+self.auth['token'], 'Content-Type': 'application/json'},
            data=None if body is None else json.dumps(body).encode())
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as response:
            b = response.read()
            return json.loads(b) if b else None

    def kub(self, args, obj=None, optional=False):
        args = list(args)
        if optional:
            args += ['--ignore-not-found']
        p = subprocess.run(self.k+args, input=None if obj is None else json.dumps(obj).encode(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        require(p.returncode == 0, 'Kubernetes operation failed; inspect locally without dumping secrets')
        return p.stdout

    def get(self, kind, name, ns=NS, optional=False):
        out = self.kub(['-n', ns, 'get', kind, name, '-o', 'json'], optional=optional)
        return json.loads(out) if out.strip() else None

    def save(self):
        atomic(self.state_path, self.state)

    def write(self, method, path, body):
        require(self.apply, 'plan attempted mutation')
        require(not self.state.get('pending'), 'uncertain previous write')
        self.state['pending'] = {'method': method, 'path': path}
        self.save()
        response = self.api(method, path, body)
        del self.state['pending']; self.save(); self.changed = True
        return response

    def create(self, obj):
        self.state['pending'] = {'kubernetes_create': obj['kind'], 'name': obj['metadata']['name']}
        self.save()
        out = self.kub(['create', '-f', '-', '-o', 'json'], obj)
        del self.state['pending']; self.save(); self.changed = True
        return json.loads(out)

    def guard(self):
        groups = self.api('GET', 'groups')
        self.admin = unique(groups, 'name', ADMIN)
        self.group = unique(groups, 'name', DEST)
        require(self.admin['issued'] == 'jwt' and not self.admin.get('resources'), 'real JWT admin source required')
        require(self.group['issued'] == 'api' and not self.group.get('resources'), 'dedicated machine destinations required')
        net = unique(self.api('GET', 'networks'), 'name', NETWORK)
        self.network = net['id']
        routers = self.api('GET', 'networks/'+self.network+'/routers')
        require(len(routers) == 1 and not routers[0].get('peer')
                and routers[0]['peer_groups'] == [self.group['id']]
                and routers[0]['enabled'] and routers[0]['masquerade'] and routers[0]['metric'] == 80,
                'native group-router drift')
        cluster = self.get('namespace', 'kube-system', ns='default')['metadata']['uid']
        namespace = self.get('namespace', NS, ns='default')['metadata']['uid']
        binding = {'cluster_uid': cluster, 'namespace_uid': namespace, 'network_id': self.network,
                   'router_id': routers[0]['id'], 'admin_id': self.admin['id'], 'group_id': self.group['id']}
        require(self.state.get('scope', binding) == binding, 'cluster/account/scope binding changed')
        self.state['scope'] = binding
        policies = self.api('GET', 'policies')
        all_id = unique(groups, 'name', 'All')['id']
        for policy in policies:
            for rule in policy.get('rules', []):
                if policy.get('enabled') and rule.get('enabled') and rule.get('action') == 'accept':
                    endpoints = (rule.get('sources') or []) + (rule.get('destinations') or [])
                    require(all_id not in {g['id'] if isinstance(g, dict) else g for g in endpoints},
                            'All-device grant violates enrollment default deny')
        require(any(policy_ok(p, self.admin['id'], group=self.group['id']) for p in policies),
                'admin own-node INPUT policy missing or broadened')
        return policies

    def status(self, host):
        value = json.loads(self.kub(['-n', NS, 'exec', 'deployment/machine-'+host,
                                     '--', 'netbird', 'status', '--json']))
        require(value['daemonStatus'] == 'Connected', 'agent not connected')
        return {'ip': str(ipaddress.ip_interface(value['netbirdIp']).ip), 'key': value['publicKey']}

    def peer_for_status(self, host):
        status = self.status(host)
        p = unique(self.api('GET', 'peers'), 'ip', status['ip'])
        require(p['connected'] and not p['user_id'] and not p['approval_required']
                and not p['login_expired'] and bool(p['hostname']) and p['name'] == 'machine-'+host,
                'machine peer identity/admission mismatch')
        return p, status

    def verify_deployment(self, host, d):
        expected = manifests(host, self.config['image'])[1]
        spec = d['spec']['template']['spec']; want = expected['spec']['template']['spec']
        require(d['spec']['replicas'] == 1 and spec['nodeSelector'] == want['nodeSelector']
                and spec['hostNetwork'] and spec['automountServiceAccountToken'] is False
                and len(spec['containers']) == 1, 'agent placement/config drift')
        c, wc = spec['containers'][0], want['containers'][0]
        require(c['image'] == wc['image'] and c['env'] == wc['env']
                and c['volumeMounts'] == wc['volumeMounts']
                and c['securityContext'] == wc['securityContext'], 'agent image/env/security drift')
        require(spec['volumes'] == want['volumes'], 'persistent identity volumes drift')

    def reconcile(self, host, seed=None):
        require(host in self.config['nodes'], 'host not enabled in inventory')
        policies = self.guard()
        known = {v['peer_id'] for v in self.state['nodes'].values() if v.get('peer_id')}
        known |= {v['id'] for v in (seed or {}).get('nodes', {}).values() if v.get('id')}
        require(member_ids(self.group) <= known, 'unbound machine-group member: explicit initial adoption required')
        node = self.get('node', host, ns='default', optional=True)
        if node is None or not any(c['type'] == 'Ready' and c['status'] == 'True' for c in node.get('status', {}).get('conditions', [])):
            return {'changed': False, 'status': 'deferred-node-not-ready', 'node': host}
        address = self.config['nodes'][host]
        entry = self.state['nodes'].get(host)
        if entry:
            require(entry['phase'] == 'ready', 'incomplete enrollment: inspect private state, never reissue automatically')
            require(entry['node_uid'] == node['metadata']['uid'] and entry['address'] == address,
                    'node reinstallation/address change requires explicit retirement')
        d = self.get('deployment', 'machine-'+host, optional=True)
        pvc = self.get('pvc', 'machine-'+host, optional=True)
        if d or pvc:
            require(d is not None and pvc is not None, 'partial/missing identity storage: refuse replacement')
            self.verify_deployment(host, d)
            p, status = self.peer_for_status(host)
            if not entry:
                require(seed is not None and seed['nodes'].get(host, {}).get('id') == p['id'],
                        'existing peer requires exact trusted migration binding, not name adoption')
        else:
            require(entry is None and not (seed or {}).get('nodes', {}).get(host), 'lost identity storage: no re-enrollment')
            require(not any(p.get('hostname') == host or p.get('name') == 'machine-'+host
                            for p in self.api('GET', 'peers')), 'orphan existing peer: no name adoption')
            if not self.apply:
                return {'changed': False, 'status': 'would-enroll-and-authorize', 'node': host}
            self.state['nodes'][host] = {'phase': 'enrolling', 'node_uid': node['metadata']['uid'], 'address': address}
            self.save()
            pvc_doc, deploy_doc = manifests(host, self.config['image'], enrollment=True)
            self.kub(['create', '--dry-run=server', '-f', '-'], pvc_doc)
            self.kub(['create', '--dry-run=server', '-f', '-'], deploy_doc)
            key = self.write('POST', 'setup-keys', {'name': 'inventory-'+host, 'type': 'one-off',
                'expires_in': 600, 'usage_limit': 1, 'auto_groups': [], 'ephemeral': False,
                'allow_extra_dns_labels': False})
            self.state['nodes'][host]['setup_key_id'] = key['id']; self.save()
            try:
                self.create({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {
                    'name': 'machine-'+host+'-enrollment', 'namespace': NS},
                    'type': 'Opaque', 'stringData': {'setup-key': key['key']}})
                pvc = self.create(pvc_doc); self.create(deploy_doc)
                self.kub(['-n', NS, 'rollout', 'status', 'deployment/machine-'+host, '--timeout=120s'])
                self.kub(['-n', NS, 'exec', 'deployment/machine-'+host, '--', 'sh', '-c',
                          'timeout 45 netbird status --check ready'])
                p, status = self.peer_for_status(host)
                d = self.get('deployment', 'machine-'+host)
                d['spec']['template']['spec']['containers'][0]['env'] = [
                    e for e in d['spec']['template']['spec']['containers'][0]['env'] if e['name'] != 'NB_SETUP_KEY']
                self.kub(['replace', '-f', '-', '-o', 'name'], d)
                self.kub(['-n', NS, 'rollout', 'status', 'deployment/machine-'+host, '--timeout=120s'])
                self.kub(['-n', NS, 'exec', 'deployment/machine-'+host, '--', 'sh', '-c',
                          'timeout 45 netbird status --check ready'])
                again, second = self.peer_for_status(host)
                require(p['id'] == again['id'] and status == second, 'identity changed on key-free restart')
            finally:
                # Revoke even when deployment fails; never leave an unattended usable key.
                self.state['cleanup'] = {'setup_key_id': key['id'], 'node': host, 'revoked': False}
                self.save()
                retired = self.api('PUT', 'setup-keys/'+key['id'], {'revoked': True, 'auto_groups': []})
                require(retired['revoked'], 'setup-key retirement failed')
                self.state['cleanup']['revoked'] = True; self.save()
                secret = self.get('secret', 'machine-'+host+'-enrollment', optional=True)
                if secret:
                    self.kub(['delete', '--raw', '/api/v1/namespaces/'+NS+'/secrets/'+secret['metadata']['name'], '-f', '-'],
                             {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'preconditions': {
                                 'uid': secret['metadata']['uid'], 'resourceVersion': secret['metadata']['resourceVersion']}})
            d = self.get('deployment', 'machine-'+host)
        binding = {'phase': 'ready', 'node_uid': node['metadata']['uid'], 'address': address,
                   'deployment_uid': d['metadata']['uid'], 'pvc_uid': pvc['metadata']['uid'],
                   'peer_id': p['id'], 'ip': status['ip'], 'public_key': status['key']}
        require(entry is None or entry == binding, 'persistent node/peer identity drift')
        require(entry is None or p['id'] in member_ids(self.group),
                'bound node removed from destination group; no automatic regrant')
        local = json.loads(self.kub(['-n', NS, 'exec', 'deployment/machine-'+host,
                                     '--', 'ip', '-j', 'address', 'show', 'dev', 'wg-socrat']))
        require(any(a.get('local') == address for i in local for a in i.get('addr_info', [])),
                'inventory WG address is not on the actual node')
        # Only Ready targets are required: an offline node is not mistaken for a broken mesh.
        nodes = json.loads(self.kub(['get', 'nodes', '-o', 'json']))['items']
        ready = {n['metadata']['name'] for n in nodes if any(c['type'] == 'Ready' and c['status'] == 'True'
                 for c in n['status']['conditions'])}
        if p['id'] not in member_ids(self.group):
            for h in sorted(ready & self.config['nodes'].keys()):
                self.kub(['-n', NS, 'exec', 'deployment/machine-'+host, '--',
                          'ping', '-n', '-c', '1', '-W', '3', self.config['nodes'][h]])
        resources_path = 'networks/'+self.network+'/resources'
        resources = self.api('GET', resources_path)
        found = [r for r in resources if r['address'] == address+'/32']
        require(len(found) <= 1, 'duplicate WG host resources')
        resource = found[0] if found else None
        if resource:
            require(resource['name'] == 'wg-'+host and resource['enabled'] and resource['type'] == 'host'
                    and not resource.get('groups'), 'existing resource scope drift')
        matching = []
        if resource:
            matching = [v for v in policies if any((r.get('destinationResource') or {}).get('id') == resource['id']
                        for r in v['rules']) and v['name'].startswith('admin-wg-')]
            require(len(matching) <= 1, 'duplicate managed resource policies')
            if matching:
                require(policy_ok(matching[0], self.admin['id'], resource=resource['id']), 'admin resource policy drift')
        grant = self.state.get('grants', {}).get(host)
        if grant:
            require(resource is not None and resource['id'] == grant['resource_id']
                    and matching and matching[0]['id'] == grant['policy_id'],
                    'managed grant removed/replaced: explicit review required, no resurrection')
        elif entry:
            require(seed is not None and seed['nodes'].get(host, {}).get('id') == p['id']
                    and resource and matching, 'legacy binding needs explicit grant-ID migration')
        if self.apply:
            self.state['nodes'][host] = dict(binding, phase='admitting'); self.save()
            if entry is None or grant is None:
                self.changed = True
            if p['id'] not in member_ids(self.group):
                fresh = self.api('GET', 'groups/'+self.group['id'])
                require(member_ids(fresh) == member_ids(self.group) and not fresh.get('resources')
                        and fresh['issued'] == 'api' and fresh['name'] == DEST, 'concurrent machine-group change')
                self.write('PUT', 'groups/'+self.group['id'], {'name': DEST, 'resources': [],
                           'peers': sorted(member_ids(self.group) | {p['id']})})
            if resource is None:
                resource = self.write('POST', resources_path, {'name': 'wg-'+host,
                    'description': 'Inventory WG node; no broader prefix', 'address': address+'/32', 'enabled': True})
        if self.apply:
            if not matching:
                matching = [self.write('POST', 'policies', policy_body(self.admin['id'], resource['id']))]
            self.state.setdefault('grants', {})[host] = {'resource_id': resource['id'], 'policy_id': matching[0]['id']}
            self.state['nodes'][host] = binding; self.save()
        return {'changed': self.changed, 'status': 'ready' if self.apply else 'validated-plan', 'node': host}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--node')
    parser.add_argument('--adopt-state', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    folder = args.state_dir
    require(folder.is_dir() and not folder.is_symlink() and not folder.stat().st_mode & 0o077,
            'private state directory required')
    with (folder/'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        c = json.loads(args.config.read_text())
        runtime = Runtime(folder, c, args.apply)
        seed = json.loads(args.adopt_state.read_text()) if args.adopt_state else None
        require(args.node is not None, 'explicit selected inventory node required')
        print(json.dumps(runtime.reconcile(args.node, seed)))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'status': 'blocked', 'error_type': type(e).__name__,
                          'reason': str(e) if isinstance(e, ValueError) else 'inspect private state; output intentionally redacted'}))
        sys.exit(1)
