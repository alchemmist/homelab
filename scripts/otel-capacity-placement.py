"""Pin Rancher Fleet controller pods to specific nodes for OTEL capacity."""
import argparse
import copy
import json
import os
import subprocess
from pathlib import Path

# gitjob and helmops are Rancher Fleet controllers. They stay while multi-cluster-management is enabled.
TARGETS = [
    ("cattle-fleet-system", "gitjob"),
    ("cattle-fleet-system", "helmops"),
    ("cattle-capi-system", "capi-controller-manager"),
    ("cattle-turtles-system", "rancher-turtles-controller-manager"),
]
NODES = ["socrat-0", "socrat-1"]


def placement(document):
    metadata, spec = document["metadata"], document["spec"]
    if (metadata["namespace"], metadata["name"]) not in TARGETS:
        message = "Deployment outside the explicit stateless-controller allowlist"
        raise ValueError(message)
    if (
        spec.get("paused")
        or spec.get("strategy", {}).get("type", "RollingUpdate") != "RollingUpdate"
    ):
        message = "Paused or non-rolling deployment needs separate handling"
        raise ValueError(message)
    desired = spec.get("replicas", 1)
    if desired < 1 or document.get("status", {}).get("readyReplicas", 0) < desired:
        message = "Controller is not healthy before capacity placement"
        raise ValueError(message)
    pod = spec["template"]["spec"]
    if any(
        any(key in volume for key in ("persistentVolumeClaim", "hostPath", "nfs"))
        for volume in pod.get("volumes", [])
    ):
        message = "Refusing to relocate a controller with persistent/local data"
        raise ValueError(message)
    if any(
        c.get("imagePullPolicy", "IfNotPresent") != "IfNotPresent"
        for c in pod["containers"] + pod.get("initContainers", [])
    ):
        message = "Warm-image-only rollout requires IfNotPresent"
        raise ValueError(message)
    pin = pod.get("nodeSelector", {}).get("kubernetes.io/hostname")
    if pin is not None and pin not in NODES:
        message = "Existing hostname pin conflicts with the large-node placement"
        raise ValueError(message)
    original = copy.deepcopy(pod.get("affinity"))
    affinity = copy.deepcopy(original or {})
    required = {
        "requiredDuringSchedulingIgnoredDuringExecution": {
            "nodeSelectorTerms": [
                {
                    "matchExpressions": [
                        {"key": "kubernetes.io/hostname", "operator": "In", "values": NODES}
                    ]
                }
            ]
        }
    }
    if affinity.get("nodeAffinity") not in (None, required):
        message = "Existing node affinity requires explicit reconciliation"
        raise ValueError(message)
    affinity["nodeAffinity"] = required
    if original == affinity:
        return None, None
    patch = {
        "metadata": {"resourceVersion": metadata["resourceVersion"]},
        "spec": {
            "strategy": {
                "type": "RollingUpdate",
                "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
            },
            "template": {"spec": {"affinity": affinity}},
        },
    }
    rollback = {
        "uid": metadata["uid"],
        "originalAffinity": original,
        "originalStrategy": copy.deepcopy(spec.get("strategy")),
        "appliedAffinity": affinity,
    }
    return patch, rollback


def run(kubeconfig, state_directory):
    state_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    base = ["k3s", "kubectl", "--kubeconfig", kubeconfig]

    def command(arguments) -> str:
        return subprocess.check_output(base + arguments, text=True, timeout=200)

    nodes = json.loads(command(["get", "nodes", "-o", "json"]))
    ready = {
        n["metadata"]["name"]
        for n in nodes["items"]
        if not n["spec"].get("unschedulable")
        and any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"])
    }
    if not set(NODES) <= ready:
        message = "Both large nodes must be Ready and schedulable"
        raise ValueError(message)
    result = []
    for namespace, name in TARGETS:
        get = ["-n", namespace, "get", "deployment", name, "-o", "json"]
        document = json.loads(command(get))
        patch, rollback = placement(document)
        if patch is None:
            result.append({"namespace": namespace, "name": name, "changed": False})
            continue
        with (state_directory / (namespace + "-" + name + ".json")).open("x") as stream:
            json.dump(rollback, stream, indent=2)
        args = [
            "-n",
            namespace,
            "patch",
            "deployment",
            name,
            "--type=merge",
            "-p",
            json.dumps(patch),
        ]
        command(args + ["--dry-run=server"])
        command(args)
        try:
            command(["-n", namespace, "rollout", "status", "deployment/" + name, "--timeout=180s"])
            live = json.loads(command(get))
            pods = json.loads(command(["-n", namespace, "get", "pods", "-o", "json"]))
            replicasets = json.loads(command(["-n", namespace, "get", "replicasets", "-o", "json"]))
            owners = {
                rs["metadata"]["uid"]
                for rs in replicasets["items"]
                if any(
                    o["uid"] == live["metadata"]["uid"]
                    for o in rs["metadata"].get("ownerReferences", [])
                )
            }
            active = [
                p
                for p in pods["items"]
                if p["status"]["phase"] == "Running"
                and not p["metadata"].get("deletionTimestamp")
                and any(o["uid"] in owners for o in p["metadata"].get("ownerReferences", []))
            ]
            if not active or any(p["spec"].get("nodeName") not in NODES for p in active):
                message = "Controller has not moved entirely to the large nodes"
                raise ValueError(message)
            result.append(
                {
                    "namespace": namespace,
                    "name": name,
                    "changed": True,
                    "nodes": sorted({p["spec"]["nodeName"] for p in active}),
                }
            )
        except Exception as exc:
            live = json.loads(command(get))
            if (
                live["metadata"]["uid"] != rollback["uid"]
                or live["spec"]["template"]["spec"].get("affinity") != rollback["appliedAffinity"]
            ):
                message = "Concurrent placement change: manual rollback required"
                raise RuntimeError(message) from exc
            restore = {
                "metadata": {"resourceVersion": live["metadata"]["resourceVersion"]},
                "spec": {
                    "strategy": rollback["originalStrategy"],
                    "template": {"spec": {"affinity": rollback["originalAffinity"]}},
                },
            }
            command(
                [
                    "-n",
                    namespace,
                    "patch",
                    "deployment",
                    name,
                    "--type=merge",
                    "-p",
                    json.dumps(restore),
                ]
            )
            command(["-n", namespace, "rollout", "status", "deployment/" + name, "--timeout=180s"])
            raise
    return {
        "schemaVersion": 1,
        "controllers": result,
        "persistentWorkloadsMoved": False,
        "memoryBudgetsReduced": False,
        "metricsOwnershipChanged": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubeconfig", default="/etc/rancher/k3s/k3s.yaml")
    parser.add_argument("--state-directory", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(run(args.kubeconfig, args.state_directory)))


if __name__ == "__main__":
    main()
