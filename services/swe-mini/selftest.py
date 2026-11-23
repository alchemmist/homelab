"""Real upstream loop + local OpenAI-compatible stub, no external inference."""

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import worker

calls: list[dict[str, object]] = []
if sys.platform == "linux":
    worker.RESULT_KEY = "a" * 64  # synthetic fixture, not a real job key
    worker.harden_parent()
    probe = """import os
assert 'RESULT_KEY' not in os.environ
try:
    open('/proc/%d/environ').read()
except PermissionError:
    pass
else:
    raise AssertionError('Child can inspect trusted parent')
""" % os.getpid()
    subprocess.run([sys.executable, "-c", probe], check=True)
    print("Parent-only result authority and /proc isolation PASS")


class Handler(BaseHTTPRequestHandler):
    """HTTP handler accepting swe-mini selftest jobs."""

    def do_POST(self) -> None:
        """Execute one self-test step from the request body."""
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert not request.get("tools"), "Venice route must not use tool-call emulation"
        calls.append(request)
        command = (
            "printf autonomous > proof.txt"
            if len(calls) == 1
            else "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        )
        payload = {
            "id": "local-test",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "```mswea_bash_command\n" + command + "\n```",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *args) -> None:
        """Suppress default request-line logging."""


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with tempfile.TemporaryDirectory() as tmp:
        worker.ROOT = Path(tmp) / "repo"
        worker.ART = Path(tmp) / "artifacts"
        worker.ROOT.mkdir()
        worker.ART.mkdir()
        (worker.ART / "task.txt").write_text("Create proof.txt containing autonomous and submit.")
        os.environ.update(
            LLM_BASE=f"http://127.0.0.1:{server.server_port}/v1",
            LLM_KEY="local-only-test",
        )
        worker.agent_main()
        result = json.loads((worker.ART / "agent-exit.json").read_text())
        assert result["exit_status"] == "Submitted", result
        assert (worker.ROOT / "proof.txt").read_text() == "autonomous"
        assert len(calls) == 2, len(calls)
        print(
            "Real mini-swe-agent text-based loop: shell execution + autonomous continuation + explicit submission PASS"
        )
finally:
    server.shutdown()
