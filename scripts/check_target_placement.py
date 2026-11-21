#!/usr/bin/env python3
"""Bounded read-only convergence check; replica0 or old Ready Pods never pass."""

import argparse
import json
import shlex
import subprocess
import time
from typing import cast


def converged(
    deployment: dict[str, object],
    pods: list[dict[str, object]],
    node: str,
    replicas: int = 1,
):
    metadata = cast("dict[str, object]", deployment["metadata"])
    spec = cast("dict[str, object]", deployment["spec"])
    status = cast("dict[str, object]", deployment.get("status", {}))
    if replicas < 1 or spec.get("replicas") != replicas:
        return False
    if cast("int", status.get("observedGeneration", 0)) < cast(
        "int", metadata["generation"]
    ):
        return False
    if status.get("updatedReplicas", 0) != replicas or status.get("readyReplicas", 0) != replicas:
        return False
    if status.get("replicas", 0) != replicas or status.get("availableReplicas", 0) != replicas:
        return False
    if status.get("unavailableReplicas", 0):
        return False
    if len(pods) != replicas:
        return False
    for pod in pods:
        pod_metadata = cast("dict[str, object]", pod["metadata"])
        pod_spec = cast("dict[str, object]", pod["spec"])
        if pod_metadata.get("deletionTimestamp") or cast("str | None", pod_spec.get("nodeName")) != node:
            return False
        state = cast("dict[str, object]", pod.get("status", {}))
        if state.get("phase") != "Running" or not any(
            cast("dict[str, object]", c).get("type") == "Ready"
            and cast("dict[str, object]", c).get("status") == "True"
            for c in cast("list[object]", state.get("conditions", []))
        ):
            return False
        states = cast("list[dict[str, object]]", state.get("containerStatuses", []))
        if len(states) != len(cast("list[object]", pod_spec["containers"])) or not all(
            c.get("ready") for c in states
        ):
            return False
    return True


def owned_by_current_revision(
    deployment: dict[str, object],
    replica_sets: list[dict[str, object]],
    pods: list[dict[str, object]],
):
    """Label match and old ReplicaSet ownership alone do not prove current rollout."""
    metadata = cast("dict[str, object]", deployment["metadata"])
    uid = metadata.get("uid")
    revision = cast("dict[str, object]", metadata.get("annotations", {})).get(
        "deployment.kubernetes.io/revision"
    )
    if not uid or not revision or not pods:
        return False

    def controller(obj: dict[str, object], kind: str, expected: set[object]):
        owners = [
            o
            for o in cast(
                "list[dict[str, object]]",
                cast("dict[str, object]", obj["metadata"]).get("ownerReferences", []),
            )
            if o.get("controller")
        ]
        return (
            len(owners) == 1
            and owners[0].get("kind") == kind
            and owners[0].get("uid") in expected
        )

    owned = {
        cast("dict[str, object]", r["metadata"])["uid"]
        for r in replica_sets
        if cast("dict[str, object]", r["metadata"]).get("uid")
        and controller(r, "Deployment", {uid})
        and cast(
            "dict[str, object]", cast("dict[str, object]", r["metadata"]).get("annotations", {})
        ).get("deployment.kubernetes.io/revision")
        == revision
    }
    return all(controller(pod, "ReplicaSet", owned) for pod in pods)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--namespace", required=True)
    p.add_argument("--deployment", required=True)
    p.add_argument("--node", required=True)
    p.add_argument("--host", default="socrat-0")
    p.add_argument(
        "--local",
        action="store_true",
        help="Read Kubernetes on this host without nested SSH; intended for Ansible script transport",
    )
    p.add_argument("--kubeconfig", default="/etc/rancher/k3s/k3s.yaml")
    p.add_argument("--timeout", type=int, default=300)
    args = p.parse_args()
    if args.timeout < 1 or args.timeout > 1800:
        p.error("timeout must be 1..1800 seconds")
    deadline = time.monotonic() + args.timeout

    def get(kind: str, *extra: str):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Placement did not converge before deadline")
        command = [
            "kubectl",
            "--kubeconfig=" + args.kubeconfig,
            "--request-timeout=15s",
            "-n",
            args.namespace,
            "get",
            kind,
            *extra,
            "-o",
            "json",
        ]
        transport = (
            command
            if args.local
            else [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                args.host,
                shlex.join(command),
            ]
        )
        result = subprocess.run(
            transport, capture_output=True, text=True, timeout=min(remaining, 25)
        )
        if result.returncode:
            raise RuntimeError(
                "Read-only Kubernetes inspection failed; inspect transport privately"
            )
        return json.loads(result.stdout)

    while time.monotonic() < deadline:
        d = get("deployment", args.deployment)
        selector = d["spec"]["selector"]
        if selector.get("matchExpressions"):
            raise ValueError("Complex selector unsupported; refusing partial ownership check")
        labels = ",".join(k + "=" + v for k, v in sorted(selector["matchLabels"].items()))
        pods = get("pods", "-l", labels)["items"]
        if converged(d, pods, args.node):
            # Validate ownership as well as labels. A manually labelled Pod is not proof.
            sets = get("replicasets", "-l", labels)["items"]
            if not owned_by_current_revision(d, sets, pods):
                raise ValueError("Ready Pod not owned by target Deployment")
            print(
                f"{args.deployment}: one Ready owned Pod on {args.node}; observed desired generation"
            )
            return
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise TimeoutError("Placement did not converge before deadline; not accepted")


if __name__ == "__main__":
    main()
