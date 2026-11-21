"""Exercise real queue state transitions with API/model boundaries mocked."""

import base64
import importlib.util
import io
import json
import os
import sys
import unittest
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2] / "services/swe-mini"


def module(name: str) -> ModuleType:
    """Load local source; module identity does not certify dynamic member signatures."""
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    if spec is None or spec.loader is None:
        message = "Queue fixture source has no usable module spec or loader"
        raise ImportError(message)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


policy = module("policy")
with (
    patch.dict(
        sys.modules,
        {
            "policy": policy,
            "jwt": MagicMock(),
            "requests": MagicMock(),
            "kubernetes": MagicMock(),
        },
    ),
    patch.dict(os.environ, {"STATE_PATH": ":memory:"}),
):
    c = module("controller")


class QueueTransitions(unittest.TestCase):
    """Tests for swe-mini queue state transitions."""

    def setUp(self) -> None:
        """Install guards and a single "work" run with mocked cluster clients."""
        # A transition regression must never reach credential files or the real API.
        github_guard = patch.object(
            c,
            "github",
            side_effect=AssertionError("Real GitHub access forbidden in queue fixtures"),
        )
        github_guard.start()
        self.addCleanup(github_guard.stop)
        c.NEXT_IDLE_CHECK = 0
        c.DB.execute("DELETE FROM runs")
        c.DB.execute(
            "INSERT INTO runs (id,lane,revision,state,job,created) VALUES ('test','backend',?,'work','test-work',0)",
            ("a" * 40,),
        )
        c.DB.commit()
        c.CORE = MagicMock()
        c.BATCH = MagicMock()
        c.BATCH.read_namespaced_job.return_value.status = SimpleNamespace(succeeded=1, failed=0)
        c.CORE.list_namespaced_pod.return_value.items = [
            SimpleNamespace(metadata=SimpleNamespace(name="worker"))
        ]
        self.result = {
            "revision": "a" * 40,
            "agent_status": "Submitted",
            "agent_rc": 0,
            "checks": {"backend": 0},
            "baseline": {"backend": 0},
            "changes": [],
            "report": "evidence",
            "candidate_checks": {"backend": 0},
        }

    def state(self) -> str:
        """Return the current state of the fixture run."""
        return cast("str", c.DB.execute("SELECT state FROM runs WHERE id='test'").fetchone()[0])

    def tick(self) -> None:
        """Feed a signed worker result into the controller and run a tick."""
        c.CORE.read_namespaced_pod_log.return_value = policy.encode_result(
            self.result, c.signing_key("test", self.state())
        )
        c.tick()

    def test_clean_no_finding_done(self) -> None:
        """A clean run with matching baseline transitions to done."""
        self.tick()
        assert self.state() == "done"

    def test_failed_baseline_never_published(self) -> None:
        """A failed baseline on the worker lands in rejected, not publishing."""
        self.result["baseline"]["backend"] = 1
        self.tick()
        assert self.state() == "rejected"

    def test_failed_postcheck_rejected(self) -> None:
        """A failing candidate post-check rejects the run."""
        self.result["checks"]["backend"] = 1
        self.tick()
        assert self.state() == "rejected"

    def test_model_limit_not_completion(self) -> None:
        """Model LimitsExceeded status marks the run failed, not done."""
        self.result["agent_status"] = "LimitsExceeded"
        self.tick()
        assert self.state() == "failed"

    def test_wrong_revision_failed(self) -> None:
        """A result for a different revision fails the run."""
        self.result["revision"] = "b" * 40
        self.tick()
        assert self.state() == "failed"

    def test_candidate_requires_review(self) -> None:
        """A run with candidate changes enters review instead of publishing."""
        self.result["changes"] = [
            {"path": "server/app/a.py", "content": base64.b64encode(b"x=1\n").decode()}
        ]
        with patch.object(c, "start_job") as start:
            self.tick()
            assert start.call_args.args[1] == "review"
            assert self.state() != "publishing"

    def test_review_rejection(self) -> None:
        """A disapproved review rejects the run."""
        c.save("test", state="review")
        self.result["review"] = {"approved": False, "reason": "reproduction fails"}
        self.tick()
        assert self.state() == "rejected"

    def test_review_approval_queues_publication(self) -> None:
        """An approved review queues publication and clears the landing config map."""
        c.save("test", state="review")
        self.result["review"] = {"approved": True, "reason": "test reproduced"}
        self.tick()
        assert self.state() == "publishing"
        c.CORE.delete_namespaced_config_map.assert_called_once()

    def test_model_approval_cannot_override_fresh_candidate_test_failure(self) -> None:
        """Review approval cannot override a fresh candidate test failure."""
        c.save("test", state="review")
        self.result["candidate_checks"] = {"backend": 1}
        self.result["review"] = {"approved": True, "reason": "model claims it passes"}
        self.tick()
        assert self.state() == "rejected"

    def test_forged_unsigned_worker_result_is_refused(self) -> None:
        """Unsigned worker results are refused outright."""
        c.CORE.read_namespaced_pod_log.return_value = policy.encode_result(self.result)
        c.tick()
        assert self.state() == "failed"

    def test_invalid_candidate_is_terminal_not_infinite_retry(self) -> None:
        """An invalid candidate ends in rejected rather than retrying forever."""
        self.result["changes"] = [{"path": ".github/workflows/evil.yml", "content": "dHJ1ZQ=="}]
        self.tick()
        assert self.state() == "rejected"

    def test_no_unstructured_log_completion(self) -> None:
        """Plain prose log output does not count as a completion marker."""
        c.CORE.read_namespaced_pod_log.return_value = "I am done!"
        c.tick()
        assert self.state() == "failed"

    def test_pending_job_is_not_restarted(self) -> None:
        """A still-running job is left alone instead of being restarted."""
        c.BATCH.read_namespaced_job.return_value.status = SimpleNamespace(
            succeeded=None, failed=None
        )
        with patch.object(c, "start_job") as start:
            c.tick()
            start.assert_not_called()
        assert self.state() == "work"

    def test_expired_job_fails_and_next_task_is_admitted(self) -> None:
        """A vanished job fails and the next queued task is admitted."""

        class NotFound(Exception):
            status = 404

        c.client.ApiException = NotFound
        c.BATCH.read_namespaced_job.side_effect = NotFound()
        c.tick()
        assert self.state() == "failed"
        with patch.object(c, "github", side_effect=[[], {"sha": "b" * 40}]):
            c.tick()
        assert c.DB.execute("SELECT count(*) FROM runs WHERE state='queued'").fetchone()[0] == 1

    def test_missing_terminal_pod_does_not_wedge_queue(self) -> None:
        """A missing terminal pod fails the run instead of wedging the queue."""
        c.CORE.list_namespaced_pod.return_value.items = []
        c.tick()
        assert self.state() == "failed"

    def test_dependency_pr_blocks_duplicates_until_base_changes(self) -> None:
        """Dependency PRs block duplicates until the base revision moves."""
        payload = {"changes": [{"path": p} for p in policy.DEPENDENCY_PATHS]}
        c.save(
            "test",
            state="published",
            pr="https://github.com/example/pr",
            result=json.dumps(payload),
        )
        prs = [
            {
                "html_url": "https://github.com/example/pr",
                "head": {"ref": "swe-mini/test"},
            }
        ]
        with patch.object(c, "github", side_effect=[prs, {"sha": "a" * 40}]):
            c.tick()
        assert c.STATUS["state"] == "waiting_for_dependency_merge"
        assert c.DB.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
        c.NEXT_IDLE_CHECK = 0
        with patch.object(c, "github", side_effect=[prs, {"sha": "b" * 40}]):
            c.tick()
        # A second idle run is recorded for the dependency merge wait.
        run_count = 2
        assert c.DB.execute("SELECT count(*) FROM runs").fetchone()[0] == run_count

    def test_idle_github_failure_is_backed_off(self) -> None:
        """Idle-path API failures are backed off rather than spammed."""
        c.save("test", state="failed")
        with patch.object(c, "github", side_effect=RuntimeError("external API unavailable")) as api:
            with self.assertRaises(RuntimeError):
                c.tick()
            c.tick()
            assert api.call_count == 1

    def test_main_discovery_uses_installation_auth(self) -> None:
        """Discovery calls GitHub with installation authentication."""
        c.save("test", state="failed")
        with patch.object(c, "github", side_effect=[[], {"sha": "b" * 40}]) as api:
            c.tick()
            assert api.call_args.kwargs.get("auth")

    def test_backoff_preserves_dependency_error_and_heartbeat(self) -> None:
        """Backoff keeps the last error visible while heartbeats continue."""
        c.save("test", state="failed")
        with patch.object(c, "github", side_effect=RuntimeError("external API unavailable")):
            c.run_once()
            c.run_once()
        assert c.STATUS["error"] == "RuntimeError"
        assert c.STATUS["last_tick"] > 0
        c.NEXT_IDLE_CHECK = 0
        with patch.object(c, "github", side_effect=[[], {"sha": "b" * 40}]):
            c.run_once()
        assert c.STATUS["error"] == ""

    def test_api_error_does_not_fail_process_health(self) -> None:
        """API errors do not fail liveness; stale heartbeats still do."""
        import threading
        import time
        import urllib.error
        import urllib.request

        saved = dict(c.STATUS)
        server = c.HTTPServer(("127.0.0.1", 0), c.Health)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def status(path) -> int:
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:%d%s" % (server.server_port, path), timeout=3
                ) as r:
                    status: int = r.status
                    return status
            except urllib.error.HTTPError as exc:
                code: int = exc.code
                exc.close()
                return code

        try:
            c.STATUS.update(last_tick=time.time(), error="HTTPError")
            http_ok = 200
            service_unavailable = 503
            assert status("/livez") == http_ok
            assert status("/healthz") == http_ok
            assert status("/dependencies") == service_unavailable
            # Liveness flips once the last tick is older than the three-minute staleness cap.
            stale_tick_seconds = 181
            c.STATUS["last_tick"] = time.time() - stale_tick_seconds
            assert status("/livez") == service_unavailable
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            c.STATUS.clear()
            c.STATUS.update(saved)

    def test_persisted_queued_run_resumes(self) -> None:
        """A persisted queued run resumes into the work lane after restart."""
        c.save("test", state="queued")
        with patch.object(c, "start_job") as start:
            c.tick()
            assert start.call_args.args[1] == "work"

    def test_paused_queue_does_not_admit_new_work(self) -> None:
        """Pause stops discovery without touching already recorded durable runs."""
        c.save("test", state="failed")
        with (
            patch.dict(os.environ, {"PAUSED": "true"}),
            patch.object(c, "github", side_effect=AssertionError("Provider forbidden")) as api,
        ):
            c.tick()
        api.assert_not_called()
        assert c.STATUS["state"] == "paused"
        assert c.DB.execute("SELECT count(*) FROM runs").fetchone()[0] == 1

    def test_paused_queue_still_resumes_existing_work(self) -> None:
        """Pause must not orphan an existing queued run or invoke a provider."""
        c.save("test", state="queued")
        with (
            patch.dict(os.environ, {"PAUSED": "true"}),
            patch.object(c, "start_job") as start,
        ):
            c.tick()
        start.assert_called_once()
        assert start.call_args.args[1] == "work"


class LoaderContract(unittest.TestCase):
    """Refuse incomplete loaders before source creation or execution."""

    def test_absent_spec_is_refused_before_module_creation(self) -> None:
        """Do not delegate a missing spec to importlib or execute fallback source."""
        with (
            patch.object(importlib.util, "spec_from_file_location", return_value=None),
            patch.object(importlib.util, "module_from_spec") as create,
        ):
            try:
                module("fixture")
            except ImportError as error:
                error_message = str(error)
            else:
                message = "Incomplete loader must be refused"
                raise AssertionError(message)
        create.assert_not_called()
        assert "no usable module spec or loader" in error_message

    def test_absent_loader_is_refused_before_module_creation(self) -> None:
        """A spec object alone is not proof that source can be safely loaded."""
        spec = ModuleSpec("fixture", loader=None)
        with (
            patch.object(importlib.util, "spec_from_file_location", return_value=spec),
            patch.object(importlib.util, "module_from_spec") as create,
        ):
            try:
                module("fixture")
            except ImportError as error:
                error_message = str(error)
            else:
                message = "Incomplete loader must be refused"
                raise AssertionError(message)
        create.assert_not_called()
        assert "no usable module spec or loader" in error_message


class HealthContract(unittest.TestCase):
    """Exercise real GET routing with no server, sockets, provider or controller loop."""

    def test_heartbeat_and_dependency_status_are_distinct(self) -> None:
        """API errors do not restart a live process; stale heartbeats still fail."""
        cases = [
            ("/livez", "RuntimeError", 10, 200),
            ("/healthz", "RuntimeError", 10, 200),
            ("/dependencies", "RuntimeError", 10, 503),
            ("/dependencies", "", 10, 200),
            ("/livez", "", 180, 503),
            ("/healthz", "", 180, 503),
            ("/dependencies", "", 180, 503),
        ]
        for path, error, age, expected in cases:
            with (
                self.subTest(path=path, error=error, age=age),
                patch.object(c.time, "time", return_value=1000),
                patch.dict(c.STATUS, {"last_tick": 1000 - age, "error": error}),
                patch("socket.socket", side_effect=AssertionError("Socket use forbidden")),
                patch.object(c, "github", side_effect=AssertionError("Provider use forbidden")),
            ):
                handler = MagicMock(spec=c.Health)
                handler.path = path
                handler.wfile = io.BytesIO()
                c.Health.do_GET(handler)
                handler.send_response.assert_called_once_with(expected)
                handler.end_headers.assert_called_once_with()
                assert json.loads(handler.wfile.getvalue())["error"] == error


if __name__ == "__main__":
    unittest.main()
