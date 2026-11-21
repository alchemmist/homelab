#!/usr/bin/env python3
"""Guarded source-only worker handoff. No workflow calls or credentials emitted.
Run with the controller Ansible Python (PyYAML), existing SSH socrat-0 identity.
Only one selected worker Deployment/Service is ever applied; broker/RBAC/code
ConfigMaps and n8n are not reconciled. Service pause is deliberate maintenance.
"""

import argparse
import json
import os
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKERS = {
    "blog": ("blog-updates-worker", "deploy/blog-updates/worker.yaml"),
    "wiki": ("wiki-openapi-worker", "deploy/wiki-openapi/worker.yaml"),
}
K = ["kubectl", "--kubeconfig=/etc/rancher/k3s/k3s.yaml"]


def call(args: list[str], data: str | None = None, timeout: int = 40) -> str:
    """Run one kubectl command over SSH; fail loudly with the operator-visible tail."""
    r = subprocess.run(
        ["ssh", "socrat-0", shlex.join(K + args)],
        input=data,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if r.returncode:
        raise RuntimeError("kubectl failed: " + r.stderr[-400:])
    return r.stdout


def get(args: list[str]) -> dict[str, object]:
    """Run one kubectl query and decode its JSON answer."""
    return cast("dict[str, object]", json.loads(call(args + ["-o", "json"])))


def worker_pods(name: str) -> list[dict[str, object]]:
    """List the pods of one worker app in the automation namespace."""
    return cast(
        "list[dict[str, object]]",
        get(["get", "pods", "-n", "automation", "-l", "app=" + name])["items"],
    )


def idle(pod: str, seconds: int = 900) -> None:
    """Prove the original worker PID1 is at a sustained single-handler-thread idle."""
    # PID1 is the original Python HTTP server, NOT this probe process. Handler
    # threads include in-progress and lock-queued stages. Never read payloads.
    code = "from pathlib import Path; assert Path('/proc/1/comm').read_text().strip().startswith('python'); print(len(list(Path('/proc/1/task').iterdir())))"
    limit = time.monotonic() + seconds
    consecutive = 0
    while time.monotonic() < limit:
        count = int(call(["exec", pod, "-n", "automation", "--", "python", "-c", code]))
        consecutive = consecutive + 1 if count == 1 else 0
        if consecutive >= 3:
            return
        time.sleep(0.25 if count == 1 else 2)
    raise RuntimeError("Worker did not reach a proven idle checkpoint")


def has_ready_endpoints(slices: dict[str, object]) -> bool:
    """Return whether any EndpointSlice of the Service still has a ready endpoint."""
    return any(
        cast("dict[str, object]", e).get("addresses")
        and cast("dict[str, object]", cast("dict[str, object]", e).get("conditions") or {}).get(
            "ready"
        )
        is not False
        for s in cast("list[object]", slices.get("items") or [])
        for e in cast("list[object]", cast("dict[str, object]", s).get("endpoints") or [])
    )


def selected_documents(stream_path: Path, kind: str | None, name: str) -> list[dict[str, object]]:
    """Return the YAML documents of one stream matching kind (if given) and name."""
    return [
        x
        for x in cast("list[dict[str, object]]", list(yaml.safe_load_all(stream_path.read_text())))
        if x
        and (kind is None or x.get("kind") == kind)
        and cast("dict[str, object]", x.get("metadata", {})).get("name") == name
    ]


def require_single_recreate_worker(deployment: dict[str, object]) -> None:
    """Refuse non-single or rolling workers; only a Recreate single can hand off."""
    spec = cast("dict[str, object]", deployment["spec"])
    if spec.get("strategy") != {"type": "Recreate"} or spec.get("replicas") != 1:
        raise RuntimeError("Single Recreate worker required")
    template = cast("dict[str, object]", spec.get("template", {}))
    inner = cast("dict[str, object]", template.get("spec", {}))
    if inner.get("nodeSelector") != {"kubernetes.io/hostname": "socrat-5"}:
        raise RuntimeError("Unexpected destination")


def require_clear_old_worker(pods: list[dict[str, object]]) -> None:
    """Refuse ambiguous old state: exactly one pod and not yet on the destination."""
    pod = pods[0]
    metadata = cast("dict[str, object]", pod["metadata"])
    spec = cast("dict[str, object]", pod["spec"])
    if len(pods) != 1 or metadata.get("deletionTimestamp"):
        raise RuntimeError("Ambiguous old worker")
    if spec.get("nodeName") == "socrat-5":
        raise RuntimeError("Already on5; inspect, do not replay maintenance")


def wait_quiesced(name: str, timeout: int = 30) -> None:
    """Block until the worker Service has no ready endpointslices left."""
    limit = time.monotonic() + timeout
    while True:
        slices = get(
            [
                "get",
                "endpointslices",
                "-n",
                "automation",
                "-l",
                "kubernetes.io/service-name=" + name,
            ]
        )
        if not has_ready_endpoints(slices):
            break
        if time.monotonic() > limit:
            raise RuntimeError("Service did not quiesce")
        time.sleep(0.25)


def require_single_new_worker(pods: list[dict[str, object]]) -> None:
    """Refuse any old/new overlap; require the one new pod on the destination."""
    pod = pods[0]
    metadata = cast("dict[str, object]", pod["metadata"])
    spec = cast("dict[str, object]", pod["spec"])
    if len(pods) != 1 or spec.get("nodeName") != "socrat-5" or metadata.get("deletionTimestamp"):
        raise RuntimeError("Expected exactly one new worker on5, no old overlap")


def write_receipt(path: Path, receipt: dict[str, object]) -> None:
    """Append the private migration receipt once, then emit it to the operator."""
    with path.open("x") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt), flush=True)


def main() -> None:
    """Drain one stateless worker safely to its new node, with a private receipt."""
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument("worker", choices=WORKERS)
    p.add_argument("--receipt-directory", type=Path, required=True)
    args = p.parse_args()
    name, path = WORKERS[args.worker]
    worker_docs = [
        x for x in cast("list[object]", list(yaml.safe_load_all((ROOT / path).read_text()))) if x
    ]
    deployment = next(
        x
        for x in cast("list[dict[str, object]]", worker_docs)
        if x.get("kind") == "Deployment"
        and cast("dict[str, object]", x["metadata"]).get("name") == name
    )
    service_document = next(
        x
        for x in cast("list[dict[str, object]]", worker_docs)
        if x.get("kind") == "Service"
        and cast("dict[str, object]", x["metadata"]).get("name") == name
    )
    require_single_recreate_worker(deployment)
    drain = next(
        iter(
            selected_documents(
                ROOT / "deploy/migrations/vm105-four-stateless-20261116/drain-services.yaml",
                None,
                name,
            )
        )
    )
    old = worker_pods(name)
    require_clear_old_worker(old)
    old_name = cast("str", cast("dict[str, object]", old[0]["metadata"])["name"])
    idle(old_name)  # no Service pause while waiting for a long stage
    receipt: dict[str, object] = {
        "worker": name,
        "oldPod": old_name,
        "oldNode": cast("dict[str, object]", old[0]["spec"])["nodeName"],
        "initialIdle": True,
        "sourceRevision": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
    }
    args.receipt_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt_path = args.receipt_directory / (args.worker + "-handoff-private.json")
    if receipt_path.exists():
        raise RuntimeError("Refusing receipt overwrite")
    paused = False
    try:
        # Set before apply: even a partial/uncertain response restores canonical
        # service in finally. No other Service or namespace-wide selector change.
        paused = True
        call(["apply", "-f", "-"], json.dumps(drain))
        receipt["pauseAt"] = datetime.now(UTC).isoformat()
        wait_quiesced(name)
        idle(old_name)  # accepted connections finish; no hard SIGTERM mid-stage
        receipt["drainedIdle"] = True
        call(["apply", "-f", "-"], json.dumps(deployment))
        call(
            ["rollout", "status", "deployment/" + name, "-n", "automation", "--timeout=180s"],
            timeout=195,
        )
        new = worker_pods(name)
        require_single_new_worker(new)
        health = "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=5); assert r.status==200; print('HEALTH200')"
        call(
            [
                "exec",
                cast("str", cast("dict[str, object]", new[0]["metadata"])["name"]),
                "-n",
                "automation",
                "--",
                "python",
                "-c",
                health,
            ]
        )
        receipt["newPod"] = cast("dict[str, object]", new[0]["metadata"])["name"]
        receipt["success"] = True
    finally:
        if paused:
            call(["apply", "-f", "-"], json.dumps(service_document))
            receipt["restoredAt"] = datetime.now(UTC).isoformat()
            receipt["canonicalServiceRestored"] = True
        write_receipt(receipt_path, receipt)


if __name__ == "__main__":
    main()
