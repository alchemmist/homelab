"""One LMS certification step per request. n8n calls this only when Qwen is idle."""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, "/app")
from idle_step import advance

ROOT = Path(os.environ.get("STATE_DIR", "/state"))
QUEUE = Path(os.environ.get("QUEUE_FILE", "/tasks/queue.json"))
TOKEN = os.environ["WORKER_TOKEN"]
BASE = os.environ.get("LITELLM_BASE", "http://litellm.llm.svc.cluster.local:4000/v1").rstrip("/")
MODEL = os.environ.get("LITELLM_MODEL", "qwen3.8-27b")


def log(event, **fields):
    print(json.dumps({"service": "lms-certify", "event": event, **fields}, ensure_ascii=False), flush=True)


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False))
    tmp.replace(path)


def run_python(source, stdin):
    with tempfile.TemporaryDirectory(prefix="lms-") as folder:
        path = Path(folder) / "main.py"
        path.write_text(source)
        try:
            result = subprocess.run(
                [sys.executable, "-I", str(path)],
                input=stdin.encode(),
                capture_output=True,
                timeout=2,
                cwd=folder,
                env={"PATH": "/usr/bin", "PYTHONNOUSERSITE": "1"},
            )
        except subprocess.TimeoutExpired:
            return 124, ""
        return result.returncode, result.stdout.decode("utf-8", "replace")[:4000]


def llm(role, prompt):
    body = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": 1200,
        "messages": [
            {"role": "system", "content": "Reply with one JSON object only. No markdown."},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ["LITELLM_KEY"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=80) as response:
        payload = json.load(response)
    text = payload["choices"][0]["message"].get("content") or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model json")
    return json.loads(text[start:end + 1])


def step():
    lock = ROOT / "step.lock"
    if lock.exists():
        return {"action": "busy"}
    lock.write_text("1")
    try:
        queue = load_json(QUEUE, [])
        state = load_json(ROOT / "state.json", {"tasks": {}})
        chosen = None
        for item in queue:
            record = state["tasks"].get(item["id"], {})
            if record.get("phase") not in {"certified", "needs_review"}:
                chosen = item
                break
        if chosen is None:
            log("idle", reason="queue_done", size=len(queue))
            return {"action": "idle", "reason": "queue_done", "size": len(queue)}
        record, phase = advance(
            {"statement": chosen["statement"], "tests": chosen.get("tests") or []},
            state["tasks"].get(chosen["id"]),
            llm,
            run_python,
        )
        state["tasks"][chosen["id"]] = record
        save_json(ROOT / "state.json", state)
        summary = {
            "action": "step",
            "task": chosen["id"],
            "phase": phase,
            "status": record.get("phase"),
            "reason": record.get("reason", ""),
            "cases": len(record.get("cases") or []),
        }
        log("step", **summary)
        return summary
    finally:
        lock.unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/healthz":
            self.send_error(404)
            return
        self._send({"ok": True})

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
