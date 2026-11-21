#!/usr/bin/env python3
"""Wait natural SPI drain, briefly quiesce Service, recheck before stopping.
No claim/dispatch/cancel/stage/model operation. Active work => immediate restore.
Use existing operator SSH; no credentials printed. Canonical source is committed
before reconcile is released; temporary selector hold is an explicit migration
operation, not a final Service configuration. Only SPI app reconciliation held.
"""

import json
import pathlib
import shlex
import signal
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
K = ["kubectl", "--kubeconfig=/etc/rancher/k3s/k3s.yaml"]


def call(args, timeout=40) -> str:
    r = subprocess.run(
        ["ssh", "socrat-0", shlex.join(K + args)], capture_output=True, text=True, timeout=timeout
    )
    if r.returncode:
        raise RuntimeError("Kubernetes operation failed; inspect private controller context")
    return r.stdout


def get(args) -> dict[str, object]:
    payload: object = json.loads(call(args + ["-o", "json"]))
    if not isinstance(payload, dict):
        reason = "Kubernetes returned a non-object payload"
        raise TypeError(reason)
    return payload


def patch_service(paused) -> None:
    s = get(["get", "service", "spi-triage", "-n", "automation"])
    if not isinstance(s, dict):
        reason = "Kubernetes returned a non-object service payload"
        raise TypeError(reason)
    key = "homelab.io/maintenance-serving"
    if paused == bool(s["spec"]["selector"].get(key)):
        return
    patch = [{"op": "test", "path": "/metadata/uid", "value": s["metadata"]["uid"]}]
    patch.append(
        {"op": "add", "path": "/spec/selector/homelab.io~1maintenance-serving", "value": "enabled"}
        if paused
        else {"op": "remove", "path": "/spec/selector/homelab.io~1maintenance-serving"}
    )
    call(
        [
            "patch",
            "service",
            "spi-triage",
            "-n",
            "automation",
            "--type=json",
            "-p",
            json.dumps(patch),
        ]
    )


def idle_state() -> dict[str, object]:
    code = """import sqlite3,os,time,json
c=sqlite3.connect('file:'+os.environ.get('SPI_DATABASE','/data/spi.sqlite')+'?mode=ro',uri=True);c.execute('pragma query_only=on')
a=c.execute(\"select count(*)from jobs where state in ('queued','retry','processing')\").fetchone()[0]
b=c.execute(\"select count(*)from workflow_wait_owner where phase in ('ready','waiting','running')\").fetchone()[0]
d=c.execute('select count(*)from spi_links where lease>?',(time.time(),)).fetchone()[0]
print(json.dumps({'activeOrQueuedJobs':a,'liveOwners':b,'liveLinkLeases':d}))
"""
    state: object = json.loads(
        call(["exec", "deployment/spi-triage", "-n", "automation", "--", "python", "-c", code])
    )
    if not isinstance(state, dict):
        reason = "SPI returned a non-object idle state"
        raise TypeError(reason)
    return state


def stop_signal(*_) -> None:
    raise SystemExit("Interrupted; restoring temporary hold")


def main() -> None:
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    d = get(["get", "deployment", "spi-triage", "-n", "automation"])
    if not isinstance(d, dict):
        reason = "Kubernetes returned a non-object deployment payload"
        raise TypeError(reason)
    if d["spec"]["template"]["spec"].get("nodeSelector") != {"kubernetes.io/hostname": "socrat-1"}:
        raise RuntimeError(
            "Historical one-way handoff refuses an already-migrated or unexpected worker"
        )
    a = get(["get", "application", "spi-triage", "-n", "argocd"])
    if not isinstance(a, dict):
        reason = "Kubernetes returned a non-object application payload"
        raise TypeError(reason)
    if a["metadata"].get("annotations", {}).get("argocd.argoproj.io/skip-reconcile") == "true":
        raise RuntimeError("App already held by someone else")
    limit = time.monotonic() + 1200
    iteration = 0
    while time.monotonic() < limit:
        state = idle_state()
        if not isinstance(state, dict):
            reason = "Unexpected idle-state payload"
            raise TypeError(reason)
        iteration += 1
        if iteration == 1 or iteration % 4 == 0:
            print(json.dumps({"waitingForNaturalIdle": state}), flush=True)
        if any(state.values()):
            time.sleep(10)
            continue
        held = False
        paused = False
        source_stopped = False
        try:
            call(
                [
                    "annotate",
                    "application",
                    "spi-triage",
                    "-n",
                    "argocd",
                    "argocd.argoproj.io/skip-reconcile=true",
                    "--overwrite",
                ]
            )
            held = True
            patch_service(True)
            paused = True
            deadline = time.monotonic() + 15
            while True:
                slices = get(
                    [
                        "get",
                        "endpointslices",
                        "-n",
                        "automation",
                        "-l",
                        "kubernetes.io/service-name=spi-triage",
                    ]
                )
                if not isinstance(slices, dict):
                    reason = "Kubernetes returned a non-object endpoint slice list"
                    raise TypeError(reason)
                if not any(
                    e.get("addresses") and (e.get("conditions") or {}).get("ready") is not False
                    for s in slices["items"]
                    for e in (s.get("endpoints") or [])
                ):
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("Service did not quiesce")
                time.sleep(0.15)
            state = idle_state()
            if not isinstance(state, dict):
                reason = "Unexpected idle-state payload"
                raise TypeError(reason)
            if any(state.values()):
                print(json.dumps({"newWorkWonRaceRestoringImmediately": state}), flush=True)
                continue
            p = ROOT / "deploy/spi-triage/values.yaml"
            text = p.read_text()
            if "workerReplicas:" in text:
                raise RuntimeError("Unreviewed replica override exists")
            text = (
                text.replace("maintenanceIngressPaused: false", "maintenanceIngressPaused: true")
                + "\nworkerReplicas: 0\n"
            )
            p.write_text(text)
            for cmd in [
                ["git", "add", "deploy/spi-triage/values.yaml"],
                [
                    "git",
                    "commit",
                    "-m",
                    "fix(spi): stop only naturally drained worker for sealed VM105 job-state copy",
                ],
                ["git", "fetch", "origin", "main"],
                ["git", "merge", "--no-edit", "origin/main"],
                ["git", "push", "origin", "HEAD:main"],
            ]:
                subprocess.run(cmd, cwd=ROOT, check=True)
            source_stopped = True
            print("SOURCE_STOP_PUBLISHED_AFTER_DOUBLE_IDLE_CHECK", flush=True)
            return
        finally:
            if paused and not source_stopped:
                patch_service(False)
            if held:
                call(
                    [
                        "annotate",
                        "application",
                        "spi-triage",
                        "-n",
                        "argocd",
                        "argocd.argoproj.io/skip-reconcile-",
                    ]
                )
                call(
                    [
                        "annotate",
                        "application",
                        "spi-triage",
                        "-n",
                        "argocd",
                        "argocd.argoproj.io/refresh=hard",
                        "--overwrite",
                    ]
                )
    raise RuntimeError(
        "No naturally idle window; worker remains running, no cancellation performed"
    )


if __name__ == "__main__":
    main()
