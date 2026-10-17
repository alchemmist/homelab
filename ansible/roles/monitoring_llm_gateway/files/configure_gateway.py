import argparse
import base64
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import urllib.parse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--chart-version', required=True)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--idle-timeout', type=int, default=300)
    parser.add_argument('--secret', required=True)
    args = parser.parse_args()
    env = dict(os.environ, K3S_CONFIG_FILE='/dev/null')
    kubectl = ['k3s', 'kubectl', '--kubeconfig', args.kubeconfig, '-n', args.namespace]
    helm = ['helm', '--kubeconfig', args.kubeconfig, '-n', args.namespace]

    def run(command, data=None):
        result = subprocess.run(command, input=data, capture_output=True, text=True, env=env)
        if result.returncode:
            raise RuntimeError('Cluster command failed; sensitive output withheld')
        return result.stdout

    def kube(*command):
        return json.loads(run(kubectl + list(command) + ['-o', 'json']))

    def api(base, path, token=None, payload=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(base + path, headers=headers,
                                         data=None if payload is None else json.dumps(payload).encode())
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode()

    release = json.loads(run(helm + ['list', '--filter', '^' + re.escape(args.release) + '$', '-o', 'json']))
    if len(release) != 1 or release[0]['chart'] != 'litellm-helm-' + args.chart_version:
        raise RuntimeError('Installed LiteLLM chart differs from the pinned monitoring integration version')
    values = json.loads(run(helm + ['get', 'values', args.release, '-o', 'json']))
    config = values.setdefault('proxy_config', {})
    settings = config.setdefault('litellm_settings', {})
    callbacks = settings.setdefault('callbacks', [])
    if not isinstance(callbacks, list):
        raise RuntimeError('Unsupported callback configuration; refusing to replace it')
    changed = False
    desired_strategy = {'type': 'RollingUpdate', 'rollingUpdate': {'maxUnavailable': 0, 'maxSurge': 1}}
    needs_upgrade = ('prometheus' not in callbacks
                     or settings.get('require_auth_for_metrics_endpoint') is not True
                     or values.get('strategy') != desired_strategy
                     or values.get('terminationGracePeriodSeconds', 90) < 7260)
    if needs_upgrade:
        vllm = kube('get', 'service', 'vllm')['spec']['clusterIP']
        deadline = time.monotonic() + args.idle_timeout
        idle_samples = 0
        while time.monotonic() < deadline:
            metrics = api('http://' + vllm + ':8000', '/metrics')
            samples = re.findall(r'^vllm:num_requests_(?:running|waiting)\{[^\n]*\}\s+([\d.eE+-]+)$', metrics, re.M)
            idle_samples = idle_samples + 1 if samples and all(float(value) == 0 for value in samples) else 0
            if idle_samples >= 3:
                break
            time.sleep(5)
        else:
            raise RuntimeError('Inference remained active; gateway rollout deferred')
        if 'prometheus' not in callbacks:
            callbacks.append('prometheus')
        settings['require_auth_for_metrics_endpoint'] = True
        values['strategy'] = desired_strategy
        values['terminationGracePeriodSeconds'] = max(values.get('terminationGracePeriodSeconds', 90), 7260)
        with tempfile.TemporaryDirectory(prefix='litellm-monitoring-') as directory:
            path = os.path.join(directory, 'values.json')
            with open(path, 'w') as stream:
                os.chmod(path, 0o600)
                json.dump(values, stream)
            run(helm + ['upgrade', args.release, 'oci://ghcr.io/berriai/litellm-helm',
                        '--version', args.chart_version, '--reuse-values', '-f', path,
                        '--wait', '--timeout', '10m', '--atomic', '--no-hooks'])
        changed = True
    service = kube('get', 'service', args.release)
    base = 'http://' + service['spec']['clusterIP'] + ':4000'
    master_secret = kube('get', 'secret', values.get('masterkeySecretName', 'litellm-env'))
    master = base64.b64decode(master_secret['data'][values.get('masterkeySecretKey', 'LITELLM_MASTER_KEY')]).decode()
    existing = run(kubectl + ['get', 'secret', args.secret, '--ignore-not-found', '-o', 'json'])
    if existing.strip():
        token = base64.b64decode(json.loads(existing)['data']['api-key']).decode()
        info = json.loads(api(base, '/key/info?key=' + urllib.parse.quote(token), master))
        if info.get('info', {}).get('allowed_routes') != ['/metrics']:
            raise RuntimeError('Existing monitoring key is not restricted to metrics')
    else:
        response = json.loads(api(base, '/key/generate', master,
                                  {'key_alias': 'prometheus-monitoring', 'allowed_routes': ['/metrics']}))
        token = response['key']
        manifest = {'apiVersion': 'v1', 'kind': 'Secret',
                    'metadata': {'name': args.secret, 'namespace': args.namespace},
                    'type': 'Opaque', 'stringData': {'api-key': token}}
        run(kubectl + ['apply', '-f', '-'], json.dumps(manifest))
        changed = True
    api(base, '/metrics', token)
    try:
        api(base, '/v1/models', token)
    except urllib.error.HTTPError as error:
        if error.code not in (401, 403):
            raise RuntimeError('Unexpected monitoring key permission check result') from None
    else:
        raise RuntimeError('Monitoring key unexpectedly permits model API access')
    print('changed=' + str(changed).lower())


if __name__ == '__main__':
    main()
