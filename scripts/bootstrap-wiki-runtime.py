import argparse
import base64
import json
import secrets
import shlex
import subprocess
from typing import TypedDict, Unpack


class BootstrapError(Exception):
    pass


class Kubernetes:
    def __init__(self, command: list[str]):
        self.command = command

    def run(self, *args: str, payload: dict[str, object] | None = None) -> str:
        result = subprocess.run(
            self.command + list(args),
            input=json.dumps(payload) if payload else None,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise BootstrapError(
                "kubectl failed; inspect resource permissions and availability without logging secret payloads"
            )
        return result.stdout

    def get(self, kind: str, name: str, namespace: str):
        value = self.run("-n", namespace, "get", kind, name, "--ignore-not-found", "-o", "json")
        return json.loads(value) if value.strip() else None

    def create(self, resource: Mapping[str, object]):
        self.run("create", "-f", "-", payload=resource)


class _SecretDocument(TypedDict, total=False):
    data: dict[str, str]


def encoded(value: str):
    return base64.b64encode(value.encode()).decode()


def decoded(value: str):
    try:
        return base64.b64decode(value, validate=True).decode()
    except (ValueError, UnicodeError, TypeError):
        raise BootstrapError("Invalid encoded credential in source Secret") from None


class _ResourceFields(TypedDict, total=False):
    spec: object
    data: object
    type: str


class _Resource(_ResourceFields):
    apiVersion: str
    kind: str
    metadata: dict[str, object]


def resource(kind: str, name: str, namespace: str, **fields: Unpack[_ResourceFields]) -> _Resource:
    metadata: dict[str, object] = {"name": name, "namespace": namespace}
    return {"apiVersion": "v1", "kind": kind, "metadata": metadata, **fields}


def required_data(item: _SecretDocument | None, key: str):
    value = (item or {}).get("data", {}).get(key)
    if not isinstance(value, str) or not value:
        raise BootstrapError("Required credential/configuration field is missing")
    return value


def prerequisites(_kube: Kubernetes):
    return [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "wiki"}}]


def bootstrap(kube: Kubernetes, *, skip_legacy_git: bool = False):
    infrastructure = prerequisites(kube)
    targets = [
        ("persistentvolumeclaim", "wiki-runtime-data", "wiki"),
        ("secret", "wiki-runtime-bootstrap", "wiki"),
        ("secret", "wiki-runtime-git", "wiki"),
    ]
    existing = [kube.get(*target) for target in targets]
    pvc = resource(
        "PersistentVolumeClaim",
        "wiki-runtime-data",
        "wiki",
        spec={
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "local-path",
            "resources": {"requests": {"storage": "5Gi"}},
        },
    )
    pvc["metadata"]["annotations"] = {"helm.sh/resource-policy": "keep"}
    if existing[0]:
        spec = existing[0].get("spec", {})
        if spec.get("storageClassName") != "local-path" or spec.get("accessModes") != [
            "ReadWriteOnce"
        ]:
            raise BootstrapError(
                "Existing wiki-runtime-data PVC has unexpected storage configuration"
            )
    if existing[1]:
        if len(decoded(required_data(existing[1], "token"))) < 32:
            raise BootstrapError(
                "Existing bootstrap Secret token is unexpectedly short; not overwriting it"
            )
    if existing[2]:
        for key in ("id_ed25519", "known_hosts"):
            required_data(existing[2], key)
    bootstrap_secret = (
        resource(
            "Secret",
            "wiki-runtime-bootstrap",
            "wiki",
            type="Opaque",
            data={"token": encoded(secrets.token_urlsafe(48))},
        )
        if not existing[1]
        else None
    )
    git_secret = None
    if not existing[2] and not skip_legacy_git:
        key = required_data(kube.get("secret", "wiki-editor-git", "wiki"), "id_ed25519")
        decoded(key)
        hosts = required_data(kube.get("configmap", "wiki-editor-hosts", "wiki"), "known_hosts")
        git_secret = resource(
            "Secret",
            "wiki-runtime-git",
            "wiki",
            type="Opaque",
            data={"id_ed25519": key, "known_hosts": encoded(hosts)},
        )
    results = []
    for item in infrastructure:
        metadata = item["metadata"]
        namespace = metadata.get("namespace", "wiki")
        old = kube.get(item["kind"].lower(), metadata["name"], namespace)
        if not old:
            kube.create(item)
            results.append(
                metadata.get("namespace", "cluster") + "/" + metadata["name"] + ": created"
            )
    for target, old, item in zip(targets, existing, [pvc, bootstrap_secret, git_secret]):
        if not old and item is not None:
            kube.create(item)
        results.append(
            f"{target[2]}/{target[1]}: "
            + ("preserved" if old else "created" if item is not None else "skipped")
        )
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Create isolated wiki runtime storage and Secret prerequisites without changing routes or deployments"
    )
    parser.add_argument(
        "--kubectl",
        default="k3s kubectl",
        help="Executable and arguments, for example kubectl --kubeconfig /path/config",
    )
    parser.add_argument("--skip-legacy-git", action="store_true")
    args = parser.parse_args()
    try:
        command = shlex.split(args.kubectl)
        if not command:
            raise BootstrapError("kubectl command must not be empty")
        for line in bootstrap(Kubernetes(command), skip_legacy_git=args.skip_legacy_git):
            print(line)
    except (BootstrapError, OSError, json.JSONDecodeError):
        parser.exit(
            1,
            "Wiki runtime bootstrap failed; no secret values were printed. Check required source resources and existing target configuration.\n",
        )


if __name__ == "__main__":
    main()
