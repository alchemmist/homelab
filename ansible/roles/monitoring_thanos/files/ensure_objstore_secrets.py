import base64
import json
import secrets
import subprocess
import sys


def kubectl(binary, kubeconfig, namespace, args, payload=None):
    command = [binary, 'kubectl', '--kubeconfig', kubeconfig, '-n', namespace, *args]
    result = subprocess.run(command, input=payload, text=True, capture_output=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def exists(binary, kubeconfig, namespace, name):
    result = subprocess.run(
        [binary, 'kubectl', '--kubeconfig', kubeconfig, '-n', namespace, 'get', 'secret', name],
        text=True, capture_output=True,
    )
    return result.returncode == 0


def read_secret(binary, kubeconfig, namespace, name):
    raw = kubectl(binary, kubeconfig, namespace, ['get', 'secret', name, '-o', 'json'])
    data = json.loads(raw)['data']
    return {key: base64.b64decode(value).decode() for key, value in data.items()}


def apply_secret(binary, kubeconfig, namespace, name, data):
    body = {
        'apiVersion': 'v1',
        'kind': 'Secret',
        'metadata': {'name': name, 'namespace': namespace},
        'type': 'Opaque',
        'stringData': data,
    }
    kubectl(binary, kubeconfig, namespace, ['apply', '-f', '-'], json.dumps(body))


def filesystem_config(directory):
    return 'type: FILESYSTEM\nconfig:\n  directory: ' + directory + '\n'




def ensure(binary, kubeconfig, namespace):
    created = []
    if not exists(binary, kubeconfig, namespace, 'thanos-objstore-raw'):
        apply_secret(binary, kubeconfig, namespace, 'thanos-objstore-raw', {
            'objstore.yml': filesystem_config('/var/lib/socrat-thanos'),
        })
        created.append('thanos-objstore-raw')
    if not exists(binary, kubeconfig, namespace, 'thanos-shelf-token'):
        apply_secret(binary, kubeconfig, namespace, 'thanos-shelf-token', {
            'token': secrets.token_urlsafe(32),
        })
        created.append('thanos-shelf-token')
    print('created' if created else 'present')
    return created


def main():
    binary, kubeconfig, namespace = sys.argv[1:4]
    ensure(binary, kubeconfig, namespace)
    return 0


if __name__ == '__main__':
    sys.exit(main())
