"""Durable single-writer queue. GitHub credentials never reach agent pods."""

import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import hashlib
import hmac
import secrets
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import cast
import uuid
import zlib

import jwt
import requests
from kubernetes import client, config
from policy import (
    LANES,
    decode_result,
    validate_changes,
    dependency_repair,
    validate_dependency_update,
)

NS = os.getenv("NAMESPACE", "swe-mini")
REPO = "alchemmist/monori"
DB = sqlite3.connect(os.getenv("STATE_PATH", "/state/queue.sqlite"), check_same_thread=False)
DB.execute(
    "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, lane TEXT, revision TEXT, state TEXT, job TEXT, result TEXT, review TEXT, pr TEXT, created REAL)"
)
DB.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
DB.execute(
    "INSERT OR IGNORE INTO metadata (key,value) VALUES (?,?)",
    ("result-master-key", secrets.token_hex(32)),
)
DB.commit()
RESULT_MASTER = bytes.fromhex(
    DB.execute("SELECT value FROM metadata WHERE key=?", ("result-master-key",)).fetchone()[0]
)
SESSION = requests.Session()
SESSION.headers["Accept"] = "application/vnd.github+json"
TOKEN = {"value": "", "expires": 0}
STATUS = {"state": "starting", "last_tick": time.time(), "error": ""}
NEXT_IDLE_CHECK: float = 0


def signing_key(run_id, phase):
    return hmac.new(RESULT_MASTER, f"{run_id}:{phase}".encode(), hashlib.sha256).hexdigest()


def github(path, method="GET", data=None, auth=True):
    headers = {}
    if auth:
        if cast("float", TOKEN["expires"]) < time.time():
            app_id = Path("/github/github-app-id").read_text().strip()
            key = Path("/github/github-private-key").read_text()
            signed = jwt.encode(
                {"iat": int(time.time()) - 30, "exp": int(time.time()) + 540, "iss": app_id},
                key,
                algorithm="RS256",
            )
            h = {"Authorization": "Bearer " + signed}
            r = SESSION.get(
                f"https://api.github.com/repos/{REPO}/installation", headers=h, timeout=30
            )
            r.raise_for_status()
            installation = r.json()["id"]
            r = SESSION.post(
                f"https://api.github.com/app/installations/{installation}/access_tokens",
                headers=h,
                json={
                    "repositories": ["monori"],
                    "permissions": {"contents": "write", "pull_requests": "write"},
                },
                timeout=30,
            )
            r.raise_for_status()
            TOKEN.update(value=r.json()["token"], expires=time.time() + 3000)
        headers["Authorization"] = "Bearer " + cast("str", TOKEN["value"])
    response = SESSION.request(
        method, "https://api.github.com/" + path, headers=headers, json=data, timeout=40
    )
    response.raise_for_status()
    return response.json() if response.content else {}


def save(run_id, **fields):
    DB.execute(
        "UPDATE runs SET " + ",".join(key + "=?" for key in fields) + " WHERE id=?",
        [*fields.values(), run_id],
    )
    DB.commit()
    if "state" in fields:
        logging.info("Run %s state=%s", run_id, fields["state"])


def start_job(run, phase):
    run_id, lane, revision = run["id"], run["lane"], run["revision"]
    name = f"swe-{run_id}-{phase}"
    volumes: list[dict[str, object]] = [{"name": "work", "emptyDir": {"sizeLimit": "8Gi"}}]
    mounts: list[dict[str, object]] = [{"name": "work", "mountPath": "/workspace"}]
    if phase == "review":
        cm_name = name + "-proposal"
        payload = json.loads(run["result"])
        cm = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=cm_name, labels={"app": "swe-mini-artifact"}),
            data={
                "proposal.json": json.dumps(
                    {"changes": payload["changes"], "report": payload["report"]}
                )
            },
        )
        try:
            CORE.create_namespaced_config_map(NS, cm)
        except client.ApiException as e:
            if e.status != 409:
                raise
        volumes.append({"name": "proposal", "configMap": {"name": cm_name}})
        mounts.append({"name": "proposal", "mountPath": "/proposal", "readOnly": True})
    recent = DB.execute(
        "SELECT lane,pr,result FROM runs WHERE state IN ('published','done','rejected') ORDER BY created DESC LIMIT 12"
    ).fetchall()
    history = "\n".join(
        f"{r[0]} {r[1]} {json.loads(r[2] or '{}').get('report', '')[:1600]}" for r in recent
    )
    pod = {
        "metadata": {"labels": {"app": "swe-mini-worker", "phase": phase}},
        "spec": {
            "nodeSelector": {"kubernetes.io/hostname": "socrat-5"},
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "serviceAccountName": "swe-mini-worker",
            "imagePullSecrets": [{"name": "swe-mini-harbor-pull"}],
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 1000,
                "runAsGroup": 1000,
                "fsGroup": 1000,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "worker",
                    "image": os.environ["WORKER_IMAGE"],
                    "command": ["python", "/app/worker.py"],
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "capabilities": {"drop": ["ALL"]},
                        "readOnlyRootFilesystem": True,
                    },
                    "resources": {
                        "requests": {"cpu": "250m", "memory": "1Gi", "ephemeral-storage": "2Gi"},
                        "limits": {"cpu": "2", "memory": "5Gi", "ephemeral-storage": "9Gi"},
                    },
                    "env": [
                        {"name": k, "value": v}
                        for k, v in {
                            "LANE": lane,
                            "PHASE": phase,
                            "REVISION": revision,
                            "HISTORY": history[:20000],
                            "RESULT_KEY": signing_key(run_id, phase),
                            "HOME": "/workspace",
                            "TMPDIR": "/workspace/tmp",
                            "UV_CACHE_DIR": "/workspace/.cache/uv",
                            "LLM_BASE": "http://litellm.llm.svc.cluster.local:4000/v1",
                        }.items()
                    ]
                    + [
                        {
                            "name": "LLM_KEY",
                            "valueFrom": {
                                "secretKeyRef": {"name": "swe-mini-model", "key": "api-key"}
                            },
                        }
                    ],
                    "volumeMounts": mounts,
                }
            ],
            "volumes": volumes,
        },
    }
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "labels": {"app": "swe-mini-worker"}},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 6900,
            "ttlSecondsAfterFinished": 3600,
            "template": pod,
        },
    }
    try:
        BATCH.create_namespaced_job(NS, job)
    except client.ApiException as e:
        if e.status != 409:
            raise
    save(run_id, state=phase, job=name)


def publish(run, result, review):
    changes = validate_changes(result["changes"])
    branch = "swe-mini/" + run["id"]
    # Deterministic branch is recovery journal: reconcile existing PR after a controller crash.
    existing = github(f"repos/{REPO}/pulls?state=all&head=alchemmist:{branch}")
    if existing:
        return existing[0]["html_url"]
    base = github(f"repos/{REPO}/git/commits/" + run["revision"])
    tree = []
    for item in changes:
        blob = github(
            f"repos/{REPO}/git/blobs", "POST", {"content": item["content"], "encoding": "base64"}
        )
        tree.append({"path": item["path"], "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree = github(
        f"repos/{REPO}/git/trees", "POST", {"base_tree": base["tree"]["sha"], "tree": tree}
    )
    commit = github(
        f"repos/{REPO}/git/commits",
        "POST",
        {
            "message": f"fix: autonomous {run['lane']} improvement ({run['id']})",
            "tree": tree["sha"],
            "parents": [run["revision"]],
        },
    )
    try:
        github(
            f"repos/{REPO}/git/refs", "POST", {"ref": "refs/heads/" + branch, "sha": commit["sha"]}
        )
    except requests.HTTPError as exc:
        response = exc.response
        if response is None or response.status_code != 422:
            raise
        # Never force-update a branch that might have acquired human edits.
        ref = github(f"repos/{REPO}/git/ref/heads/" + branch)
        current = github(f"repos/{REPO}/git/commits/" + ref["object"]["sha"])
        if current["tree"]["sha"] != tree["sha"] or [p["sha"] for p in current["parents"]] != [
            run["revision"]
        ]:
            raise ValueError("Existing candidate branch differs; refusing publication") from exc
    body = (
        "Automated by mini-swe-agent v2.4.6; owner approval required. No production access or merge.\n\n"
        + result["report"][:16000]
        + "\n\n## Deterministic post-check exit codes\n```json\n"
        + json.dumps(result["checks"])
        + "\n```\n## Independent fresh-container review\n"
        + str(review["review"].get("reason", ""))[:7000]
        + f"\n\nRun `{run['id']}`, base `{run['revision']}`. Model review is not a security guarantee. Full private run record is retained in the queue database."
    )
    pr = cast(
        "dict[str, object]",
        github(
            f"repos/{REPO}/pulls",
            "POST",
            {
                "title": f"[mini] {run['lane']}: tested small improvement",
                "head": branch,
                "base": "main",
                "body": body,
                "draft": False,
            },
        ),
    )
    return pr["html_url"]


def tick() -> bool | None:
    global NEXT_IDLE_CHECK
    active = DB.execute(
        "SELECT * FROM runs WHERE state IN ('queued','work','review','publishing') ORDER BY created LIMIT 1"
    ).fetchone()
    if active:
        columns = [r[1] for r in DB.execute("PRAGMA table_info(runs)")]
        run = dict(zip(columns, active, strict=True))
        if run["state"] == "queued":
            start_job(run, "work")
            return None
        if run["state"] == "publishing":
            url = publish(run, json.loads(run["result"]), json.loads(run["review"]))
            save(run["id"], state="published", pr=url)
            return None
        try:
            job = BATCH.read_namespaced_job(run["job"], NS)
        except client.ApiException as exc:
            if exc.status != 404:
                raise
            field = "result" if run["state"] == "work" else "review"
            save(
                run["id"],
                state="failed",
                **{
                    field: json.dumps(
                        {
                            "error": "Worker Job expired or was removed; queue will continue with a fresh task"
                        }
                    )
                },
            )
            return None
        if not job.status.succeeded and not job.status.failed:
            return None
        pods = CORE.list_namespaced_pod(NS, label_selector="job-name=" + run["job"]).items
        if len(pods) != 1:
            save(
                run["id"],
                state="failed",
                review=json.dumps({"error": "Missing or ambiguous worker Pod; no publication"}),
            )
            return None
        log = CORE.read_namespaced_pod_log(pods[0].metadata.name, NS, limit_bytes=2_000_000)
        try:
            result = decode_result(log, signing_key(run["id"], run["state"]))
        except (KeyError, TypeError, ValueError, OSError, zlib.error):
            if run["state"] == "review":
                try:
                    CORE.delete_namespaced_config_map(run["job"] + "-proposal", NS)
                except client.ApiException as exc:
                    if exc.status != 404:
                        raise
            save(
                run["id"],
                state="failed",
                review=json.dumps({"error": "Missing worker result; inspect job status"}),
            )
            return None
        if run["state"] == "review":
            try:
                CORE.delete_namespaced_config_map(run["job"] + "-proposal", NS)
            except client.ApiException as exc:
                if exc.status != 404:
                    raise
        field = "result" if run["state"] == "work" else "review"
        save(run["id"], **{field: json.dumps(result)})
        if (
            result.get("error")
            or result.get("revision") != run["revision"]
            or result.get("agent_status") != "Submitted"
            or result.get("agent_rc") != 0
        ):
            save(run["id"], state="failed")
            return
        candidate = (
            result.get("changes", [])
            if run["state"] == "work"
            else json.loads(run["result"] or "{}").get("changes", [])
        )
        repair = dependency_repair(candidate)
        try:
            if candidate:
                validate_changes(candidate)
            if any(i["path"] in {"web/package.json", "web/package-lock.json"} for i in candidate):
                base = cast(
                    "dict[str, object]",
                    github(
                        f"repos/{REPO}/contents/web/package.json?ref={run['revision']}", auth=True
                    ),
                )
                validate_dependency_update(
                    candidate, json.loads(base64.b64decode(cast("str", base["content"])))
                )
                validate_dependency_update(candidate, json.loads(base64.b64decode(base["content"])))
        except (ValueError, KeyError, TypeError):
            save(run["id"], state="rejected")
            return None
        # Only a narrowly validated dependency repair may start from a red frontend install.
        baseline_ok = not any(result.get("baseline", {"missing": 1}).values())
        bootstrap_ok = (
            repair
            and result.get("setup", {}).get("node", 0) != 0
            and result.get("baseline", {}).get("backend") == 0
        )
        if (
            not result.get("checks")
            or any(result["checks"].values())
            or not (baseline_ok or bootstrap_ok)
        ):
            save(run["id"], state="rejected")
            return None
        if run["state"] == "work":
            if not result.get("changes"):
                save(run["id"], state="done")
                return
            validate_changes(result["changes"])
            run["result"] = json.dumps(result)
            start_job(run, "review")
        else:
            if (
                not result.get("candidate_checks")
                or any(result["candidate_checks"].values())
                or result.get("review", {}).get("approved") is not True
            ):
                save(run["id"], state="rejected")
            else:
                save(run["id"], state="publishing")
        return None
    if os.getenv("PAUSED", "false") == "true":
        STATUS["state"] = "paused"
        return None
    previous = DB.execute("SELECT created,lane FROM runs ORDER BY created DESC LIMIT 1").fetchone()
    latest = previous[0] if previous else 0
    if (
        previous
        and previous[1] != "smoke"
        and time.time() - latest < int(os.getenv("MIN_INTERVAL_SECONDS", "1800"))
    ):
        return None
    # Waiting is healthy; external discovery is bounded, including after failures.
    if time.monotonic() < NEXT_IDLE_CHECK:
        return False
    NEXT_IDLE_CHECK = time.monotonic() + 300
    # Backpressure: bounded open PRs. Never keep creating PRs faster than a human can review.
    prs = github(f"repos/{REPO}/pulls?state=open&per_page=100")
    if sum(p["head"]["ref"].startswith("swe-mini/") for p in prs) >= 5:
        STATUS["state"] = "waiting_for_pr_review"
        return
    revision = github(f"repos/{REPO}/commits/main", auth=True)["sha"]
    open_urls = {p["html_url"] for p in prs}
    for pr, payload in DB.execute(
        "SELECT pr,result FROM runs WHERE state='published' AND revision=? ORDER BY created DESC LIMIT 100",
        (revision,),
    ):
        if pr in open_urls and dependency_repair(json.loads(payload or "{}").get("changes", [])):
            STATUS["state"] = "waiting_for_dependency_merge"
            return None
    index = DB.execute("SELECT count(*) FROM runs").fetchone()[0]
    lane = "smoke" if index == 0 else list(LANES)[(index - 1) % len(LANES)]
    run_id = time.strftime("%y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:5]
    DB.execute(
        "INSERT INTO runs (id,lane,revision,state,created) VALUES (?,?,?,?,?)",
        (run_id, lane, revision, "queued", time.time()),
    )
    DB.commit()
    STATUS["state"] = "running"
    logging.info("Queued run %s lane=%s revision=%s", run_id, lane, revision[:12])
    return None


class Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/healthz", "/livez", "/dependencies"):
            # External API failures cannot be repaired by restarting this process.
            alive = time.time() - cast("float", STATUS["last_tick"]) < 180
            ready = alive and (self.path != "/dependencies" or not STATUS["error"])
            self.send_response(200 if ready else 503)
            payload = json.dumps(STATUS).encode()
        elif self.path == "/metrics":
            self.send_response(200)
            counts = DB.execute("SELECT state,count(*) FROM runs GROUP BY state").fetchall()
            payload = (
                "# TYPE swe_mini_runs gauge\n"
                + "\n".join(f'swe_mini_runs{{state="{s}"}} {n}' for s, n in counts)
                + "\n"
            ).encode()
        else:
            self.send_response(404)
            payload = b""
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def run_once() -> None:
    try:
        if tick() is not False:
            STATUS["error"] = ""
    except (
        client.ApiException,
        requests.RequestException,
        sqlite3.OperationalError,
        ValueError,
        KeyError,
        TypeError,
        OSError,
    ) as exc:
        # Never log bodies, tokens or raw third-party error responses.
        STATUS["error"] = type(exc).__name__
        response = getattr(exc, "response", None)
        logging.error(
            "Queue tick failed: %s status=%s; bounded retry, no process restart required",
            type(exc).__name__,
            getattr(response, "status_code", None),
        )
    finally:
        STATUS["last_tick"] = time.time()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    config.load_incluster_config()
    CORE, BATCH = client.CoreV1Api(), client.BatchV1Api()
    threading.Thread(
        target=HTTPServer(("0.0.0.0", 9090), Health).serve_forever, daemon=True
    ).start()
    while True:
        run_once()
        time.sleep(30)
