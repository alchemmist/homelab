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


def s3_config(endpoint, access_key, secret_key):
    return (
        'type: S3\n'
        'config:\n'
        '  bucket: thanos\n'
        '  endpoint: ' + endpoint + '\n'
        '  access_key: ' + access_key + '\n'
        '  secret_key: ' + secret_key + '\n'
        '  insecure: true\n'
    )


def s3_identity(access_key, secret_key):
    return json.dumps({
        'identities': [{
            'name': 'thanos',
            'credentials': [{'accessKey': access_key, 'secretKey': secret_key}],
            'actions': ['Admin', 'Read', 'Write', 'List', 'Tagging'],
        }],
    }) + '\n'


def ensure(binary, kubeconfig, namespace):
    created = []
    if not exists(binary, kubeconfig, namespace, 'thanos-objstore-raw'):
        apply_secret(binary, kubeconfig, namespace, 'thanos-objstore-raw', {
            'objstore.yml': filesystem_config('/var/lib/socrat-thanos'),
        })
        created.append('thanos-objstore-raw')
    shelves = (
        ('thanos-minio-5m-credentials', 'thanos-objstore-5m', 'thanos-minio-5m.cattle-monitoring-system.svc.cluster.local:9000'),
        ('thanos-minio-1h-credentials', 'thanos-objstore-1h', 'thanos-minio-1h.cattle-monitoring-system.svc.cluster.local:9000'),
    )
    for credentials, objstore, endpoint in shelves:
        if not exists(binary, kubeconfig, namespace, credentials):
            password = secrets.token_urlsafe(32)
            apply_secret(binary, kubeconfig, namespace, credentials, {
                'rootUser': 'thanos',
                'rootPassword': password,
                's3.json': s3_identity('thanos', password),
            })
            created.append(credentials)
        else:
            stored = read_secret(binary, kubeconfig, namespace, credentials)
            if 's3.json' not in stored:
                apply_secret(binary, kubeconfig, namespace, credentials, {
                    'rootUser': stored['rootUser'],
                    'rootPassword': stored['rootPassword'],
                    's3.json': s3_identity(stored['rootUser'], stored['rootPassword']),
                })
                created.append(credentials)
        if not exists(binary, kubeconfig, namespace, objstore):
            stored = read_secret(binary, kubeconfig, namespace, credentials)
            apply_secret(binary, kubeconfig, namespace, objstore, {
                'objstore.yml': s3_config(endpoint, stored['rootUser'], stored['rootPassword']),
            })
            created.append(objstore)
    print('created' if created else 'present')
    return created


def main():
    binary, kubeconfig, namespace = sys.argv[1:4]
    ensure(binary, kubeconfig, namespace)
    return 0


if __name__ == '__main__':
    sys.exit(main())
