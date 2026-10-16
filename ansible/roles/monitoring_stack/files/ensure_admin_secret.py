import json
import secrets
import subprocess
import sys

binary, kubeconfig, namespace, name = sys.argv[1:]
command = [binary, "kubectl", "--kubeconfig", kubeconfig, "-n", namespace]
result = subprocess.run(command + ["get", "secret", name, "--ignore-not-found", "-o", "name"], check=True, capture_output=True, text=True)
if result.stdout.strip():
    print("unchanged")
else:
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "namespace": namespace},
        "type": "Opaque",
        "stringData": {"admin-user": "admin", "admin-password": secrets.token_urlsafe(36)},
    }
    subprocess.run(command + ["create", "-f", "-"], input=json.dumps(secret), text=True, check=True, capture_output=True)
    print("created")
