import argparse
import shlex
import subprocess
import sys


REMOTE = r'''
import http.client
import json
import socket
import ssl
import subprocess
import sys

HOST = 'rancher.socrat.alchemmist.xyz'
ADDRESSES = ('10.250.0.1', '10.250.0.3')
KUBECTL = ['env', 'K3S_CONFIG_FILE=/dev/null', 'k3s', 'kubectl',
           '--kubeconfig', '/etc/rancher/k3s/k3s.yaml']


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('Probe command failed: ' + result.stderr[-500:])
    return result.stdout


def kube(*args):
    return json.loads(run(KUBECTL + list(args)))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)
    print('PASS:', message, flush=True)


def request(address, path, token=None):
    connection = http.client.HTTPSConnection(HOST, timeout=20, context=ssl.create_default_context())
    connection._create_connection = lambda target, timeout, source_address=None: socket.create_connection(
        (address, 443), timeout, source_address=('10.250.0.1', 0))
    try:
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


try:
    deployment = kube('-n', 'cattle-system', 'get', 'deployment', 'rancher', '-o', 'json')
    require(deployment['spec']['replicas'] == 2 and deployment['status'].get('readyReplicas') == 2,
            'Rancher has two ready replicas')
    pods = kube('-n', 'cattle-system', 'get', 'pods', '-l', 'app=rancher', '-o', 'json')['items']
    pods = [pod for pod in pods if not pod['metadata'].get('deletionTimestamp')]
    require(len(pods) == 2 and {pod['spec']['nodeName'] for pod in pods} == {'socrat-0', 'socrat-1'}
            and all(any(c['type'] == 'Ready' and c['status'] == 'True'
                        for c in pod['status'].get('conditions', [])) for pod in pods),
            'Rancher replicas are ready on socrat-0 and socrat-1')
    ingresses = kube('get', 'ingress', '-A', '-o', 'json')['items']
    routes = [item for item in ingresses if any(rule.get('host') == HOST
              for rule in item.get('spec', {}).get('rules', []))]
    require(not routes, 'No public Rancher ingress exists')
    for server in ('10.250.0.1', '10.250.0.3', '10.250.0.2'):
        answers = run(['dig', '+short', '+time=3', '+tries=1', '@' + server, HOST, 'A']).split()
        require(set(answers) == set(ADDRESSES), 'Private DNS ' + server + ' returns both gateways')
    expected_nodes = {node['metadata']['name'] for node in kube('get', 'nodes', '-o', 'json')['items']}
    tokens = kube('get', 'tokens.management.cattle.io', '-o', 'json')['items']
    tokens = [token for token in tokens if token.get('token') and not token.get('expired')
              and token.get('enabled') is not False]
    require(bool(tokens), 'An existing Rancher token is available for authenticated checks')
    for address in ADDRESSES:
        status, body = request(address, '/ping')
        require(status == 200 and body.strip() == b'pong', 'Trusted private HTTPS ping through ' + address)
        status, body = request(address, '/dashboard/')
        require(status == 200 and b'id="socrat-layout-fix"' in body and b'overflow-wrap: anywhere' in body, 'Scoped Rancher layout stylesheet through ' + address)
        require(b'/_socrat/rancher-layout.js' in body, 'Grafana frame sizing helper included through ' + address)
        status, body = request(address, '/_socrat/rancher-layout.js')
        require(status == 200 and b'ResizeObserver' in body and b'grid.style.height' in body, 'Grafana frame sizing helper served through ' + address)
        authenticated = False
        for token in tokens:
            credential = token['metadata']['name'] + ':' + token['token']
            status, body = request(address, '/k8s/clusters/local/v1/nodes', credential)
            if status == 200:
                data = json.loads(body).get('data', [])
                authenticated = {node['metadata']['name'] for node in data} == expected_nodes
                if authenticated:
                    break
        require(authenticated, 'Authenticated Rancher node listing through ' + address)
    for pod in pods:
        body = run(KUBECTL + ['-n', 'cattle-system', 'exec', pod['metadata']['name'], '--',
                   'curl', '--cacert', '/etc/ssl/ca-bundle.pem', '--silent', '--show-error', '--fail', '--noproxy', '*',
                   '--connect-timeout', '10', '--max-time', '20', 'https://' + HOST + '/ping'])
        require(body.strip() == 'pong', 'Pod on ' + pod['spec']['nodeName'] + ' resolves and reaches its HTTPS hostname')
except Exception as error:
    print('FAIL:', str(error), file=sys.stderr)
    sys.exit(1)
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-host', default='socrat-0')
    parser.add_argument('--external-ssh-host', default='socrat-2-direct')
    parser.add_argument('--public-address', default='109.173.40.247')
    args = parser.parse_args()
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.ssh_host, 'python3 -'],
                            input=REMOTE, text=True, timeout=240)
    if result.returncode:
        return result.returncode
    for scheme, port in [('http', 80), ('https', 443)]:
        for forwarded in [False, True]:
            command = ['curl', '--silent', '--show-error', '--noproxy', '*',
                       '--connect-timeout', '10', '--max-time', '20', '--insecure',
                       '--write-out', '\n%{http_code}', '--resolve',
                       f'rancher.socrat.alchemmist.xyz:{port}:{args.public_address}']
            if forwarded:
                command += ['--header', 'X-Forwarded-For: 10.250.0.1']
            command += [scheme + '://rancher.socrat.alchemmist.xyz/ping']
            result = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.external_ssh_host,
                                     shlex.join(command)], capture_output=True, text=True, timeout=45)
            body, _, status = result.stdout.rpartition('\n')
            if result.returncode or status != '404' or body.strip() != '404 page not found':
                print(f'FAIL: Public {scheme} did not return only the default 404 (forwarded={forwarded})',
                      file=sys.stderr)
                return 1
            print(f'PASS: Public {scheme} returns default 404 (forwarded={forwarded})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
