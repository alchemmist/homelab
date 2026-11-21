"""Bootstrap the wiki runtime resources on the Kubernetes cluster."""
import argparse
import base64
import json
import secrets
import shlex
import subprocess


class BootstrapError(Exception):
    pass


class Kubernetes:
    def __init__(self, command: list[str]) -> None:
        self.command = command

    def run(self, *args: str, payload: object | None = None) -> str:
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

    def get(self, kind: str, name: str, namespace: str) -> dict[str, object] | None:
        value = self.run("-n", namespace, "get", kind, name, "--ignore-not-found", "-o", "json")
        if not value.strip():
            return None
        resource_map: dict[str, object] = json.loads(value)
        return resource_map

    def create(self, resource: dict[str, object]) -> None:
        self.run("create", "-f", "-", payload=resource)


def encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def decoded(value: str) -> str:
    try:
        return base64.b64decode(value, validate=True).decode()
    except (ValueError, UnicodeError, TypeError):
        raise BootstrapError("Invalid encoded credential in source Secret") from None


def resource(kind: str, name: str, namespace: str, **fields: object) -> dict[str, object]:
    return {
        "apiVersion": "v1",
        "kind": kind,
        "metadata": {"name": name, "namespace": namespace},
        **fields,
    }


def required_data(item: dict[str, object] | None, key: str) -> str:
    value = (item or {}).get("data", {}).get(key)
    if not isinstance(value, str) or not value:
        raise BootstrapError("Required credential/configuration field is missing")
    return value


def prerequisites(_kube: Kubernetes) -> list[dict[str, object]]:
    return [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "wiki"}}]


def _data_pvc() -> dict[str, object]:
    """Build the helm-kept data PVC bound to the local-path storage class."""
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": "wiki-runtime-data",
            "namespace": "wiki",
            "annotations": {"helm.sh/resource-policy": "keep"},
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "local-path",
            "resources": {"requests": {"storage": "5Gi"}},
        },
    }


def _check_pvc(existing_pvc: dict[str, object] | None) -> None:
    """Reject an existing data PVC that no longer matches the storage policy."""
    if not existing_pvc:
        return
    spec = existing_pvc.get("spec")
    if isinstance(spec, dict):
        storage, modes = spec.get("storageClassName"), spec.get("accessModes")
    else:
        storage, modes = None, None
    if storage != "local-path" or modes != ["ReadWriteOnce"]:
        raise BootstrapError("Existing wiki-runtime-data PVC has unexpected storage configuration")


def _check_secrets(existing: list[dict[str, object] | None]) -> None:
    """Refuse to touch existing bootstrap/git Secrets whose payloads look damaged."""
    if existing[1] and len(decoded(required_data(existing[1], "token"))) < 32:
        raise BootstrapError(
            "Existing bootstrap Secret token is unexpectedly short; not overwriting it"
        )
    if existing[2]:
        for key in ("id_ed25519", "known_hosts"):
            required_data(existing[2], key)


def _git_secret(
    kube: Kubernetes, existing_git: dict[str, object] | None, *, skip_legacy_git: bool
) -> dict[str, object] | None:
    """Materialize the runtime git Secret from reviewed wiki-editor sources."""
    if existing_git or skip_legacy_git:
        return None
    key = required_data(kube.get("secret", "wiki-editor-git", "wiki"), "id_ed25519")
    decoded(key)
    hosts = required_data(kube.get("configmap", "wiki-editor-hosts", "wiki"), "known_hosts")
    return resource(
        "Secret",
        "wiki-runtime-git",
        "wiki",
        type="Opaque",
        data={"id_ed25519": key, "known_hosts": encoded(hosts)},
    )


def bootstrap(kube: Kubernetes, *, skip_legacy_git: bool = False) -> list[str]:
    """Create missing wiki runtime storage and Secrets; never rotate existing ones."""
    infrastructure = prerequisites(kube)
    targets = [
        ("persistentvolumeclaim", "wiki-runtime-data", "wiki"),
        ("secret", "wiki-runtime-bootstrap", "wiki"),
        ("secret", "wiki-runtime-git", "wiki"),
    ]
    existing = [kube.get(*target) for target in targets]
    pvc = _data_pvc()
    _check_pvc(existing[0])
    _check_secrets(existing)
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
    git_secret = _git_secret(kube, existing[2], skip_legacy_git=skip_legacy_git)
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
