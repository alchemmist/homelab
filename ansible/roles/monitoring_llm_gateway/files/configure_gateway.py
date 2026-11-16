"""Read-only verification of an EXISTING Git-owned gateway and metrics key.
No Helm fallback, inference, key creation, Secret apply or rollout on any path.
"""
import argparse
import base64
import ipaddress
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward an authorization header to a redirected host.


def verify(args, runner=None, opener=None):
    runner = runner or subprocess.run
    opener = opener or urllib.request.build_opener(NoRedirect()).open
    kubectl = ['k3s', 'kubectl', '--kubeconfig', args.kubeconfig,
               '--request-timeout=15s']

    def get(namespace, kind, name):
        result = runner(kubectl + ['-n', namespace, 'get', kind, name, '-o', 'json'],
                        capture_output=True, text=True, timeout=30,
                        env=dict(os.environ, K3S_CONFIG_FILE='/dev/null'))
        if result.returncode:
            raise RuntimeError('Required cluster read failed; no fallback is permitted')
        return json.loads(result.stdout)

    app = get('argocd', 'application', args.release)
    spec = app['spec']
    sources = spec.get('sources', [spec.get('source', {})])
    matching = [s for s in sources if s.get('repoURL') == 'https://github.com/alchemmist/homelab.git'
                and s.get('path') == 'charts/litellm']
    if (len(matching) != 1 or spec['destination']['namespace'] != args.namespace
            or spec['destination'].get('server') != 'https://kubernetes.default.svc'):
        raise RuntimeError('Expected Git-owned LiteLLM source/destination missing')
    if matching[0].get('helm', {}).get('releaseName', args.release) != args.release:
        raise RuntimeError('Unexpected Git-owned release name')

    deployment = get(args.namespace, 'deployment', args.release)
    if deployment['metadata']['labels'].get('helm.sh/chart') != 'litellm-helm-' + args.chart_version:
        raise RuntimeError('Deployed chart label differs; review the maintenance contract')
    refs = [e['valueFrom']['secretKeyRef']
            for c in deployment['spec']['template']['spec']['containers']
            for e in c.get('env', []) if e.get('name') == 'PROXY_MASTER_KEY'
            and 'secretKeyRef' in e.get('valueFrom', {})]
    if len(refs) != 1:
        raise RuntimeError('Expected one explicit deployed master-key reference')
    service = get(args.namespace, 'service', args.release)
    address = ipaddress.ip_address(service['spec']['clusterIP'])
    if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
        raise RuntimeError('Expected private cluster Service address')
    host = '[' + str(address) + ']' if address.version == 6 else str(address)
    base = 'http://' + host + ':4000'

    # Missing key is a prerequisite failure, never authorization to generate one.
    metrics_secret = get(args.namespace, 'secret', args.secret)
    token = base64.b64decode(metrics_secret['data']['api-key'], validate=True).decode()
    ref = refs[0]
    master_secret = get(args.namespace, 'secret', ref['name'])
    master = base64.b64decode(master_secret['data'][ref['key']], validate=True).decode()
    if not token or not master:
        raise RuntimeError('Empty existing key; refusing repair')

    def request(path, credential=None, read_json=False):
        headers = {} if credential is None else {'Authorization': 'Bearer ' + credential}
        req = urllib.request.Request(base + path, headers=headers, method='GET')
        try:
            with opener(req, timeout=30) as response:
                if response.status != 200:
                    return response.status, None
                if not read_json:
                    return 200, None
                body = response.read(65537)
                if len(body) > 65536:
                    raise RuntimeError('Oversized key metadata')
                return 200, json.loads(body)
        except urllib.error.HTTPError as error:
            return error.code, None

    status, info = request('/key/info?' + urllib.parse.urlencode({'key': token}), master, True)
    if status != 200 or info.get('info', {}).get('allowed_routes') != ['/metrics']:
        raise RuntimeError('Existing key must be restricted to metrics')
    if request('/metrics')[0] not in (401, 403):
        raise RuntimeError('Anonymous metrics must remain denied')
    if request('/metrics', token)[0] != 200:
        raise RuntimeError('Existing metrics key does not work; no repair attempted')
    if request('/v1/models', token)[0] not in (401, 403):
        raise RuntimeError('Model API must remain denied to metrics key')
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--chart-version', required=True)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--secret', required=True)
    parser.add_argument('--idle-timeout', type=int, help='Deprecated compatibility argument; no idle wait or rollout occurs')
    args = parser.parse_args()
    try:
        verify(args)
    except Exception:
        # HTTP/key-info errors may contain a token in their URL. Never echo them.
        raise SystemExit('Read-only gateway verification failed; review Git ownership and existing metrics prerequisites privately. No repair or fallback attempted.') from None
    print('changed=false')


if __name__ == '__main__':
    main()
