import json
import secrets
import subprocess
from collections.abc import Mapping
from typing import cast


def kube(
    *args: str, document: Mapping[str, object] | None = None
) -> dict[str, object] | list[object]:
    r = subprocess.run(
        ["kubectl", *args],
        input=json.dumps(document) if document else None,
        text=True,
        capture_output=True,
    )
    if r.returncode:
        raise RuntimeError("Kubernetes operation failed; sensitive output suppressed")
    data = json.loads(r.stdout) if r.stdout.strip() else {}
    return cast("dict[str, object] | list[object]", data)


existing = subprocess.run(
    ["kubectl", "-n", "lms", "get", "secret", "lms-ha-app", "-o", "name"],
    capture_output=True,
)
if existing.returncode:
    obj = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "lms-ha-app", "namespace": "lms"},
        "type": "kubernetes.io/basic-auth",
        "stringData": {"username": "lms", "password": secrets.token_urlsafe(36)},
    }
    kube("create", "-f", "-", "-o", "json", document=obj)
print(json.dumps({"applicationCredentialPrepared": True, "secretsPrinted": False}))
existing = subprocess.run(
    ["kubectl", "-n", "lms", "get", "secret", "lms-backup-key", "-o", "name"],
    capture_output=True,
)
if existing.returncode:
    obj = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "lms-backup-key", "namespace": "lms"},
        "type": "Opaque",
        "stringData": {"passphrase": secrets.token_urlsafe(48)},
    }
    kube("create", "-f", "-", "-o", "json", document=obj)
print(json.dumps({"backupEncryptionCredentialPrepared": True, "secretsPrinted": False}))
