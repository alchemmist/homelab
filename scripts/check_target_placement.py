#!/usr/bin/env python3
"""Bounded read-only convergence check; replica0 or old Ready Pods never pass."""

import argparse
import json
import shlex
import subprocess
import time


def converged(deployment, pods, node, replicas=1):
    """Document this public function."""
    spec, status = deployment["spec"], deployment.get("status", {})
    if replicas < 1 or spec.get("replicas") != replicas:
        return False
    if status.get("observedGeneration", 0) < deployment["metadata"]["generation"]:
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
        if pod["metadata"].get("deletionTimestamp") or pod["spec"].get("nodeName") != node:
            return False
        state = pod.get("status", {})
        if state.get("phase") != "Running" or not any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in state.get("conditions", [])
        ):
            return False
        states = state.get("containerStatuses", [])
        if len(states) != len(pod["spec"]["containers"]) or not all(c.get("ready") for c in states):
            return False
    return True


def owned_by_current_revision(deployment, replica_sets, pods):
    """Label match and old ReplicaSet ownership alone do not prove current rollout."""
    uid = deployment["metadata"].get("uid")
    revision = (
        deployment["metadata"].get("annotations", {}).get("deployment.kubernetes.io/revision")
    )
    if not uid or not revision or not pods:
        return False

    def controller(obj, kind, expected):
        owners = [o for o in obj["metadata"].get("ownerReferences", []) if o.get("controller")]
        return (
            len(owners) == 1 and owners[0].get("kind") == kind and owners[0].get("uid") in expected
        )

    owned = {
        r["metadata"]["uid"]
        for r in replica_sets
        if r["metadata"].get("uid")
        and controller(r, "Deployment", {uid})
        and r["metadata"].get("annotations", {}).get("deployment.kubernetes.io/revision")
        == revision
    }
    return all(controller(pod, "ReplicaSet", owned) for pod in pods)


def main():
    """Document this public function."""
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

    def get(kind, *extra):
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
