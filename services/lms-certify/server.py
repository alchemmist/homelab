"""Run one full certification loop when n8n sees Qwen idle.

The HTTP call returns as soon as the loop is started. The loop keeps the same
task across model calls, isolated runs and mutation rounds. If other requests
are waiting on vLLM, the loop saves its place and the next idle minute resumes it.
"""

import json
import os
import resource
import subprocess
import sys
import re
import tempfile
import time
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, "/app")
from certify_loop import certify

ROOT = Path(os.environ.get("STATE_DIR", "/state"))
QUEUE = Path(os.environ.get("QUEUE_FILE", "/tasks/queue.json"))
TOKEN = os.environ["WORKER_TOKEN"]
BASE = os.environ.get("LITELLM_BASE", "http://litellm.llm.svc.cluster.local:4000/v1").rstrip("/")
MODEL = os.environ.get("LITELLM_MODEL", "qwen3.8-27b")
PROMETHEUS = os.environ.get(
    "PROMETHEUS_URL",
    "http://kube-prometheus-stack-prometheus.cattle-monitoring-system.svc.cluster.local:9090",
).rstrip("/")
LOCK = ROOT / "step.lock"


def log(event, **fields):
    print(
        json.dumps({"service": "lms-certify", "event": event, **fields}, ensure_ascii=False),
        flush=True,
    )


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False))
    tmp.replace(path)


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


def run_python(source, stdin):
    """Isolated student process: fresh directory, no secrets, CPU and memory caps."""
    with tempfile.TemporaryDirectory(prefix="lms-") as folder:
        path = Path(folder) / "main.py"
        path.write_text(source)
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-B", str(path)],
                input=stdin.encode(),
                capture_output=True,
                timeout=2,
                cwd=folder,
                env={
                    "PATH": "/usr/local/bin:/usr/bin",
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                start_new_session=True,
                preexec_fn=_limits,
            )
        except subprocess.TimeoutExpired:
            return 124, ""
        return result.returncode, result.stdout.decode("utf-8", "replace")[:4000]


class ModelBusy(Exception):
    pass


def _wait_budget(detail):
    match = re.search(r"resets at: ([0-9-]{10} [0-9:]{8}) UTC", detail)
    delay = 20
    if match:
        from datetime import datetime, timezone

        reset = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        delay = min(90, max(1, int((reset - datetime.now(timezone.utc)).total_seconds()) + 1))
    log("wait_budget", seconds=delay)
    time.sleep(delay)


def llm(_role, prompt):
    body = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": 1600,
        "messages": [
            {"role": "system", "content": "Reply with one JSON object only. No markdown."},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["LITELLM_KEY"],
            "Content-Type": "application/json",
        },
    )
    for attempt in range(6):
        try:
            response = urllib.request.urlopen(request, timeout=180)
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:240]
            if exc.code == 429 and attempt < 5:
                _wait_budget(detail)
                continue
            if exc.code in {408, 409, 429, 500, 502, 503, 504}:
                raise ModelBusy(str(exc.code))
            raise
    with response:
        payload = json.load(response)
    text = payload["choices"][0]["message"].get("content") or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model json")
    return json.loads(text[start : end + 1])


def others_waiting():
    query = 'vllm:num_requests_waiting{model_name="qwen3.8-27b"}'
    url = PROMETHEUS + "/api/v1/query?query=" + urllib.request.quote(query)
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.load(response)
    except Exception:
        return False
    waiting = 0
    for row in payload.get("data", {}).get("result", []):
        waiting += float(row["value"][1])
    return waiting > 0


def open_task(queue, state):
    for item in queue:
        record = state["tasks"].get(item["id"], {})
        if record.get("loop") == "v2" and record.get("phase") in {"certified", "needs_review"}:
            continue
        return item
    return None


def run_loop(task_id, statement):
    try:
        state = load_json(ROOT / "state.json", {"tasks": {}})

        def hook(record):
            current = load_json(ROOT / "state.json", {"tasks": {}})
            current["tasks"][task_id] = record
            save_json(ROOT / "state.json", current)
            log(
                "round",
                task=task_id,
                status=record.get("phase"),
                reason=record.get("reason", ""),
                rounds=record.get("rounds"),
                cases=len(record.get("cases") or []),
            )

        record = certify(
            {"statement": statement},
            state["tasks"].get(task_id),
            llm,
            run_python,
            pause=others_waiting,
            hook=hook,
        )
        state = load_json(ROOT / "state.json", {"tasks": {}})
        state["tasks"][task_id] = record
        save_json(ROOT / "state.json", state)
        log(
            "loop",
            task=task_id,
            status=record.get("phase"),
            reason=record.get("reason", ""),
            rounds=record.get("rounds", 0),
            cases=len(record.get("cases") or []),
            killed=(record.get("mutation") or {}).get("killed"),
            mutants=(record.get("mutation") or {}).get("total"),
        )
    except ModelBusy as exc:
        log("paused", task=task_id, status=str(exc))
    except Exception as exc:
        log("error", task=task_id, kind=type(exc).__name__)
    finally:
        LOCK.unlink(missing_ok=True)


def step():
    if LOCK.exists():
        return {"action": "running"}
    queue = load_json(QUEUE, [])
    state = load_json(ROOT / "state.json", {"tasks": {}})
    chosen = open_task(queue, state)
    if chosen is None:
        log("idle", reason="queue_done", size=len(queue))
        return {"action": "idle", "reason": "queue_done", "size": len(queue)}
    ROOT.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(chosen["id"])
    threading.Thread(target=run_loop, args=(chosen["id"], chosen["statement"]), daemon=True).start()
    log("started", task=chosen["id"])
    return {"action": "started", "task": chosen["id"]}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/healthz":
            self.send_error(404)
            return
        self._send({"ok": True, "running": LOCK.exists()})

    def do_POST(self):
        if self.path != "/step" or self.headers.get("X-Worker-Token") != TOKEN:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(min(length, 1024))
        try:
            self._send(step())
        except Exception as exc:
            log("error", kind=type(exc).__name__)
            self._send({"action": "error", "kind": type(exc).__name__}, 500)

    def _send(self, payload, status=200):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
