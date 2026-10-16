import argparse
import base64
import json
import secrets
import subprocess


def kubectl(*args, input_data=None):
    return subprocess.check_output(
        ['k3s', 'kubectl', *args], input=input_data, stderr=subprocess.PIPE
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--admin-secret', required=True)
    parser.add_argument('--auth-secret', required=True)
    args = parser.parse_args()
    admin = json.loads(kubectl('-n', args.namespace, 'get', 'secret', args.admin_secret, '-o', 'json'))
    username = base64.b64decode(admin['data']['admin-user']).decode()
    password = base64.b64decode(admin['data']['admin-password']).decode()
    if any(char in username for char in ':\r\n') or any(char in password for char in '\r\n'):
        raise ValueError('Grafana credentials cannot be represented in ingress BasicAuth')
    current_raw = kubectl('-n', args.namespace, 'get', 'secret', args.auth_secret, '--ignore-not-found', '-o', 'json')
    current = json.loads(current_raw) if current_raw.strip() else {}
    old_users = base64.b64decode(current.get('data', {}).get('users', '')).decode()
    parts = old_users.strip().split('$')
    salt = parts[2] if len(parts) == 4 and parts[1] == 'apr1' else secrets.token_hex(4)
    hashed = subprocess.check_output(
        ['openssl', 'passwd', '-apr1', '-salt', salt, '-stdin'],
        input=password.encode() + b'\n', stderr=subprocess.PIPE
    ).decode().strip()
    users = username + ':' + hashed + '\n'
    if users == old_users:
        print('unchanged')
        return
    secret = {
        'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
        'metadata': {'name': args.auth_secret, 'namespace': args.namespace},
        'data': {'users': base64.b64encode(users.encode()).decode()},
    }
    kubectl('apply', '-f', '-', input_data=json.dumps(secret).encode())
    print('changed')


if __name__ == '__main__':
    main()
