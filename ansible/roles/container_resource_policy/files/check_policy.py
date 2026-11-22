"""Check that pods in a namespace comply with container resource limits."""

import argparse
import json
import os
import subprocess
import sys
from typing import cast

RESOURCE_NAMES = ("cpu", "memory", "ephemeral-storage")


def _require_case_defaults(
    case: str,
    container_type: str,
    actual: dict[str, dict[str, object]],
    resources: dict[str, dict[str, str]],
) -> None:
    """Assert one returned container matches the reviewed mutating defaulting policy."""
    for mode, keys in (
        ("requests", RESOURCE_NAMES),
        ("limits", ("memory", "ephemeral-storage")),
    ):
        if not all(key in actual.get(mode, {}) for key in keys):
            raise AssertionError((case, container_type, actual))
    limits = actual["limits"]
    if any(limits[key] == "0" for key in ("memory", "ephemeral-storage")):
        raise AssertionError((case, container_type, actual))
    if case == "zero-limits" and "cpu" in limits:
        raise AssertionError(("Zero CPU limit must be removed", case, container_type, actual))
    if case == "gpu" and limits.get("nvidia.com/gpu") != "1":
        raise AssertionError((case, container_type, actual))
    if case == "high-request" and any(
        limits.get(key) != resources["requests"][key] for key in ("memory", "ephemeral-storage")
    ):
        raise AssertionError((case, container_type, actual))
    requested = resources.get("limits", {})
    if "cpu" not in requested and "cpu" in limits:
        raise AssertionError(("Unexpected CPU cap", case, container_type, actual))
    if case == "small-limit" and actual["requests"] != resources["limits"]:
        raise AssertionError((case, container_type, actual))
    if case == "explicit" and actual != resources:
        raise AssertionError((case, container_type, actual))


def check(namespace: str, kubectl: str, kubeconfig: str) -> None:
    """Document the check operation."""
    command = [kubectl, "--kubeconfig", kubeconfig, "--request-timeout=30s"]
    cases: list[tuple[str, dict[str, dict[str, str]]]] = [
        ("empty", {}),
        ("memory-only", {"limits": {"memory": "256Mi"}}),
        ("high-request", {"requests": {"cpu": "4", "memory": "2Gi", "ephemeral-storage": "8Gi"}}),
        ("small-limit", {"limits": {"cpu": "5m", "memory": "16Mi", "ephemeral-storage": "8Mi"}}),
        ("gpu", {"limits": {"nvidia.com/gpu": "1"}}),
        ("zero-limits", {"limits": dict.fromkeys(RESOURCE_NAMES, "0")}),
        (
            "explicit",
            {
                "requests": {"cpu": "250m", "memory": "512Mi", "ephemeral-storage": "100Mi"},
                "limits": {"cpu": "6", "memory": "2Gi", "ephemeral-storage": "10Gi"},
            },
        ),
    ]
    for case, resources in cases:
        pod = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "resource-policy-check-" + case, "namespace": namespace},
            "spec": {
                "restartPolicy": "Never",
                "containers": [
                    {"name": "main", "image": "registry.k8s.io/pause:3.10", "resources": resources}
                ],
                "initContainers": [
                    {"name": "init", "image": "registry.k8s.io/pause:3.10", "resources": resources}
                ],
            },
        }
        result = subprocess.run(
            command + ["create", "--dry-run=server", "-o", "json", "-f", "-"],
            input=json.dumps(pod),
            text=True,
            capture_output=True,
            check=True,
            timeout=40,
        )
        returned = json.loads(result.stdout)
        for container_type in ("containers", "initContainers"):
            _require_case_defaults(
                case,
                container_type,
                cast(
                    "dict[str, dict[str, object]]", returned["spec"][container_type][0]["resources"]
                ),
                resources,
            )
        print(case + ": passed")
    print(
        "All 7 server-side dry-run cases passed for regular and init containers; no pods created."
    )


def main() -> None:
    """Document the main operation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--kubeconfig", default="/etc/rancher/k3s/k3s.yaml")
    args = parser.parse_args()
    os.environ.setdefault("K3S_CONFIG_FILE", "/dev/null")
    check(args.namespace, args.kubectl, args.kubeconfig)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr or error.stdout or str(error), file=sys.stderr, flush=True)
        sys.exit(1)
    except (ValueError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr, flush=True)
        sys.exit(1)
