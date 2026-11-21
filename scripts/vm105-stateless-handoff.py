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
from typing import TypedDict

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKERS = {
    "blog": ("blog-updates-worker", "deploy/blog-updates/worker.yaml"),
    "wiki": ("wiki-openapi-worker", "deploy/wiki-openapi/worker.yaml"),
}
K = ["kubectl", "--kubeconfig=/etc/rancher/k3s/k3s.yaml"]


class _EndpointConditions(TypedDict, total=False):
    ready: bool


class _Endpoint(TypedDict, total=False):
    addresses: list[str]
    conditions: _EndpointConditions


class _EndpointSlice(TypedDict, total=False):
    endpoints: list[_Endpoint]


class _EndpointSliceList(TypedDict, total=False):
    items: list[_EndpointSlice]


def call(args: list[str], data: str | None = None, timeout: int = 40):
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


def get(args: list[str]):
    return json.loads(call(args + ["-o", "json"]))


def worker_pods(name: str):
    return get(["get", "pods", "-n", "automation", "-l", "app=" + name])["items"]


def idle(pod: str, seconds: int = 900):
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


def has_ready_endpoints(slices: _EndpointSliceList):
    return any(
        e.get("addresses") and (e.get("conditions") or {}).get("ready") is not False
        for s in (slices.get("items") or [])
        for e in (s.get("endpoints") or [])
    )


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument("worker", choices=WORKERS)
    p.add_argument("--receipt-directory", type=Path, required=True)
    args = p.parse_args()
    name, path = WORKERS[args.worker]
    docs = [x for x in yaml.safe_load_all((ROOT / path).read_text()) if x]
    deployment = next(
        x for x in docs if x["kind"] == "Deployment" and x["metadata"]["name"] == name
    )
    service = next(x for x in docs if x["kind"] == "Service" and x["metadata"]["name"] == name)
    if (
        deployment["spec"]["strategy"] != {"type": "Recreate"}
        or deployment["spec"]["replicas"] != 1
    ):
        raise RuntimeError("Single Recreate worker required")
    if deployment["spec"]["template"]["spec"]["nodeSelector"] != {
        "kubernetes.io/hostname": "socrat-5"
    }:
        raise RuntimeError("Unexpected destination")
    drain = next(
        x
        for x in yaml.safe_load_all(
            (
                ROOT / "deploy/migrations/vm105-four-stateless-20261116/drain-services.yaml"
            ).read_text()
        )
        if x and x["metadata"]["name"] == name
    )
    old = worker_pods(name)
    if len(old) != 1 or old[0]["metadata"].get("deletionTimestamp"):
        raise RuntimeError("Ambiguous old worker")
    if old[0]["spec"]["nodeName"] == "socrat-5":
        raise RuntimeError("Already on5; inspect, do not replay maintenance")
    old_name = old[0]["metadata"]["name"]
    idle(old_name)  # no Service pause while waiting for a long stage
    receipt = {
        "worker": name,
        "oldPod": old_name,
        "oldNode": old[0]["spec"]["nodeName"],
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
        limit = time.monotonic() + 30
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
        idle(old_name)  # accepted connections finish; no hard SIGTERM mid-stage
        receipt["drainedIdle"] = True
        call(["apply", "-f", "-"], json.dumps(deployment))
        call(
            ["rollout", "status", "deployment/" + name, "-n", "automation", "--timeout=180s"],
            timeout=195,
        )
        new = worker_pods(name)
        if (
            len(new) != 1
            or new[0]["spec"]["nodeName"] != "socrat-5"
            or new[0]["metadata"].get("deletionTimestamp")
        ):
            raise RuntimeError("Expected exactly one new worker on5, no old overlap")
        health = "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=5); assert r.status==200; print('HEALTH200')"
        call(["exec", new[0]["metadata"]["name"], "-n", "automation", "--", "python", "-c", health])
        receipt["newPod"] = new[0]["metadata"]["name"]
        receipt["success"] = True
    finally:
        if paused:
            call(["apply", "-f", "-"], json.dumps(service))
            receipt["restoredAt"] = datetime.now(UTC).isoformat()
            receipt["canonicalServiceRestored"] = True
        with receipt_path.open("x") as f:
            json.dump(receipt, f, indent=2)
        print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
