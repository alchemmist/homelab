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
from typing import cast

ROOT = pathlib.Path(__file__).resolve().parents[1]
K = ["kubectl", "--kubeconfig=/etc/rancher/k3s/k3s.yaml"]


def call(args: list[str], timeout: int = 40) -> str:
    """Run one kubectl command over the operator SSH context and fail loudly."""
    r = subprocess.run(
        ["ssh", "socrat-0", shlex.join(K + args)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if r.returncode:
        msg = "Kubernetes operation failed; inspect private controller context"
        raise RuntimeError(msg)
    return r.stdout


def get(args: list[str]) -> dict[str, object]:
    """Run one kubectl get/... and decode its JSON answer."""
    return cast("dict[str, object]", json.loads(call([*args, "-o", "json"])))


def patch_service(*, paused: bool) -> None:
    """Add or remove the temporary per-endpoint maintenance hold selector."""
    s = get(["get", "service", "spi-triage", "-n", "automation"])
    spec = cast("dict[str, object]", s["spec"])
    selector = cast("dict[str, object]", spec["selector"])
    key = "homelab.io/maintenance-serving"
    if paused == bool(selector.get(key)):
        return
    metadata = cast("dict[str, object]", s["metadata"])
    patch = [{"op": "test", "path": "/metadata/uid", "value": metadata["uid"]}]
    patch.append(
        {
            "op": "add",
            "path": "/spec/selector/homelab.io~1maintenance-serving",
            "value": "enabled",
        }
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
    """Read the app-contract idle counters inside the running SPI container."""
    code = """import json,os,psycopg
with psycopg.connect(os.environ['SPI_POSTGRES_URL'],connect_timeout=5) as db:
    db.execute('SET TRANSACTION READ ONLY')
    name,jobs,owners,links,budgets=db.execute(\"\"\"SELECT current_database(),
      (SELECT count(*) FROM public.jobs WHERE state IN ('queued','retry','processing')),
      (SELECT count(*) FROM public.workflow_wait_owner WHERE phase IN ('ready','waiting','running')),
      (SELECT count(*) FROM public.spi_links WHERE lease>extract(epoch FROM now())),
      (SELECT count(*) FROM public.llm_admission WHERE active=1 AND expires>extract(epoch FROM now()))\"\"\").fetchone()
    if name!='spi_triage': raise RuntimeError('Unexpected database')
    print(json.dumps(dict(activeOrQueuedJobs=jobs,liveOwners=owners,liveLinkLeases=links,liveAdmissions=budgets)))
"""
    return cast(
        "dict[str, object]",
        json.loads(
            call(
                [
                    "exec",
                    "deployment/spi-triage",
                    "-n",
                    "automation",
                    "--",
                    "python",
                    "-c",
                    code,
                ]
            )
        ),
    )


def stop_signal(*_: object) -> None:
    """Turn SIGTERM/SIGINT into an interrupted stop so the finally block restores."""
    msg = "Interrupted; restoring temporary hold"
    raise SystemExit(msg)


def require_expected_worker() -> None:
    """Refuse an unexpected or already-migrated worker node placement."""
    d = get(["get", "deployment", "spi-triage", "-n", "automation"])
    spec = cast("dict[str, object]", d["spec"])
    template = cast("dict[str, object]", spec["template"])
    tspec = cast("dict[str, object]", template["spec"])
    if tspec.get("nodeSelector") != {"kubernetes.io/hostname": "socrat-1"}:
        msg = "Historical one-way handoff refuses an already-migrated or unexpected worker"
        raise RuntimeError(msg)


def require_unheld() -> None:
    """Refuse to hold when another operator already holds Argo reconciliation."""
    a = get(["get", "application", "spi-triage", "-n", "argocd"])
    metadata = cast("dict[str, object]", a["metadata"])
    annotations = cast("dict[str, object]", metadata.get("annotations", {}))
    if annotations.get("argocd.argoproj.io/skip-reconcile") == "true":
        msg = "App already held by someone else"
        raise RuntimeError(msg)


def quiesce_endpoints() -> None:
    """Block until no ready EndpoointSlice of the Service remains publishing."""
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
        if not any(
            cast("dict[str, object]", e).get("addresses")
            and cast(
                "dict[str, object]",
                cast("dict[str, object]", e).get("conditions") or {},
            ).get("ready")
            is not False
            for s in cast("list[object]", slices["items"])
            for e in cast("list[object]", cast("dict[str, object]", s).get("endpoints") or [])
        ):
            break
        if time.monotonic() > deadline:
            msg = "Service did not quiesce"
            raise RuntimeError(msg)
        time.sleep(0.15)


def publish_stopped_state() -> None:
    """Commit and push the reviewed worker-replica stop to canonical main."""
    p = ROOT / "deploy/spi-triage/values.yaml"
    text = p.read_text()
    if "workerReplicas:" in text:
        msg = "Unreviewed replica override exists"
        raise RuntimeError(msg)
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


def attempt_idle_handoff() -> bool:
    """Hold reconciliation and stop the worker; restore immediately on any problem.

    Returns True once the stopped source is published; False when new work won
    the race and the outer wait loop must drain again.
    """
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
        patch_service(paused=True)
        paused = True
        quiesce_endpoints()
        state = idle_state()
        if any(state.values()):
            print(json.dumps({"newWorkWonRaceRestoringImmediately": state}), flush=True)
            return False
        publish_stopped_state()
        source_stopped = True
        print("SOURCE_STOP_PUBLISHED_AFTER_DOUBLE_IDLE_CHECK", flush=True)
        return True
    finally:
        if paused and not source_stopped:
            patch_service(paused=False)
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


def main() -> None:
    """Drain SPI naturally, then hold reconciliation and stop the drained worker."""
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    require_expected_worker()
    require_unheld()
    limit = time.monotonic() + 1200
    iteration = 0
    while time.monotonic() < limit:
        state = idle_state()
        iteration += 1
        if iteration == 1 or iteration % 4 == 0:
            print(json.dumps({"waitingForNaturalIdle": state}), flush=True)
        if any(state.values()):
            time.sleep(10)
            continue
        if attempt_idle_handoff():
            return
    msg = "No naturally idle window; worker remains running, no cancellation performed"
    raise RuntimeError(msg)


if __name__ == "__main__":
    main()
