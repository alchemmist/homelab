import json
import subprocess
import urllib.request


def kubectl(*arguments):
    return json.loads(subprocess.check_output(
        ['kubectl', *arguments, '-o', 'json'], stderr=subprocess.DEVNULL,
    ))


def verify():
    expected = sorted(node['metadata']['name'] for node in kubectl('get', 'nodes')['items'])
    tokens = kubectl('get', 'tokens.management.cattle.io')['items']
    bindings = kubectl('get', 'globalrolebindings.management.cattle.io')['items']
    admins = {item.get('userName') for item in bindings if item.get('globalRoleName') == 'admin'}
    token = next(item for item in tokens if not item.get('expired') and item.get('token') and item.get('userId') in admins)
    authorization = 'Bearer ' + token['metadata']['name'] + ':' + token['token']
    pods = kubectl('-n', 'cattle-system', 'get', 'pods', '-l', 'app=rancher')['items']
    endpoints = [(pod['metadata']['name'], 'http://' + pod['status']['podIP']) for pod in pods]
    endpoints.append(('ingress', 'https://rancher.socrat.alchemmist.xyz'))
    for name, endpoint in endpoints:
        request = urllib.request.Request(endpoint + '/k8s/clusters/local/v1/nodes', headers={
            'Authorization': authorization,
            'Host': 'rancher.socrat.alchemmist.xyz',
            'X-Forwarded-Proto': 'https',
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        actual = sorted(node['metadata']['name'] for node in result['data'])
        print(name, 'nodes=' + ','.join(actual), 'revision=' + str(result.get('revision')))
        if actual != expected:
            raise RuntimeError('Rancher node list does not match Kubernetes on ' + name)


if __name__ == '__main__':
    verify()
