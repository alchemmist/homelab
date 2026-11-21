"""Exercise real queue state transitions with API/model boundaries mocked."""

import base64
import importlib.util
from importlib.machinery import ModuleSpec
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
from typing import cast
import unittest
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
    def setUp(self) -> None:
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
        return cast("str", c.DB.execute("SELECT state FROM runs WHERE id='test'").fetchone()[0])

    def tick(self) -> None:
        c.CORE.read_namespaced_pod_log.return_value = policy.encode_result(
            self.result, c.signing_key("test", self.state())
        )
        c.tick()

    def test_clean_no_finding_done(self) -> None:
        self.tick()
        self.assertEqual(self.state(), "done")

    def test_failed_baseline_never_published(self) -> None:
        self.result["baseline"]["backend"] = 1
        self.tick()
        self.assertEqual(self.state(), "rejected")

    def test_failed_postcheck_rejected(self) -> None:
        self.result["checks"]["backend"] = 1
        self.tick()
        self.assertEqual(self.state(), "rejected")

    def test_model_limit_not_completion(self) -> None:
        self.result["agent_status"] = "LimitsExceeded"
        self.tick()
        self.assertEqual(self.state(), "failed")

    def test_wrong_revision_failed(self) -> None:
        self.result["revision"] = "b" * 40
        self.tick()
        self.assertEqual(self.state(), "failed")

    def test_candidate_requires_review(self) -> None:
        self.result["changes"] = [
            {"path": "server/app/a.py", "content": base64.b64encode(b"x=1\n").decode()}
        ]
        with patch.object(c, "start_job") as start:
            self.tick()
            self.assertEqual(start.call_args.args[1], "review")
            self.assertNotEqual(self.state(), "publishing")

    def test_review_rejection(self) -> None:
        c.save("test", state="review")
        self.result["review"] = {"approved": False, "reason": "reproduction fails"}
        self.tick()
        self.assertEqual(self.state(), "rejected")

    def test_review_approval_queues_publication(self) -> None:
        c.save("test", state="review")
        self.result["review"] = {"approved": True, "reason": "test reproduced"}
        self.tick()
        self.assertEqual(self.state(), "publishing")
        c.CORE.delete_namespaced_config_map.assert_called_once()

    def test_model_approval_cannot_override_fresh_candidate_test_failure(self) -> None:
        c.save("test", state="review")
        self.result["candidate_checks"] = {"backend": 1}
        self.result["review"] = {"approved": True, "reason": "model claims it passes"}
        self.tick()
        self.assertEqual(self.state(), "rejected")

    def test_forged_unsigned_worker_result_is_refused(self) -> None:
        c.CORE.read_namespaced_pod_log.return_value = policy.encode_result(self.result)
        c.tick()
        self.assertEqual(self.state(), "failed")

    def test_invalid_candidate_is_terminal_not_infinite_retry(self) -> None:
        self.result["changes"] = [{"path": ".github/workflows/evil.yml", "content": "dHJ1ZQ=="}]
        self.tick()
        self.assertEqual(self.state(), "rejected")

    def test_no_unstructured_log_completion(self) -> None:
        c.CORE.read_namespaced_pod_log.return_value = "I am done!"
        c.tick()
        self.assertEqual(self.state(), "failed")

    def test_pending_job_is_not_restarted(self) -> None:
        c.BATCH.read_namespaced_job.return_value.status = SimpleNamespace(
            succeeded=None, failed=None
        )
        with patch.object(c, "start_job") as start:
            c.tick()
            start.assert_not_called()
        self.assertEqual(self.state(), "work")

    def test_expired_job_fails_and_next_task_is_admitted(self) -> None:
        class NotFound(Exception):
            status = 404

        c.client.ApiException = NotFound
        c.BATCH.read_namespaced_job.side_effect = NotFound()
        c.tick()
        self.assertEqual(self.state(), "failed")
        with patch.object(c, "github", side_effect=[[], {"sha": "b" * 40}]):
            c.tick()
        self.assertEqual(
            c.DB.execute("SELECT count(*) FROM runs WHERE state='queued'").fetchone()[0],
            1,
        )

    def test_missing_terminal_pod_does_not_wedge_queue(self) -> None:
        c.CORE.list_namespaced_pod.return_value.items = []
        c.tick()
        self.assertEqual(self.state(), "failed")

    def test_dependency_pr_blocks_duplicates_until_base_changes(self) -> None:
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
        self.assertEqual(c.STATUS["state"], "waiting_for_dependency_merge")
        self.assertEqual(c.DB.execute("SELECT count(*) FROM runs").fetchone()[0], 1)
        c.NEXT_IDLE_CHECK = 0
        with patch.object(c, "github", side_effect=[prs, {"sha": "b" * 40}]):
            c.tick()
        self.assertEqual(c.DB.execute("SELECT count(*) FROM runs").fetchone()[0], 2)

    def test_idle_github_failure_is_backed_off(self) -> None:
        c.save("test", state="failed")
        with patch.object(c, "github", side_effect=RuntimeError("external API unavailable")) as api:
            with self.assertRaises(RuntimeError):
                c.tick()
            c.tick()
            self.assertEqual(api.call_count, 1)

    def test_main_discovery_uses_installation_auth(self) -> None:
        c.save("test", state="failed")
        with patch.object(c, "github", side_effect=[[], {"sha": "b" * 40}]) as api:
            c.tick()
            self.assertTrue(api.call_args.kwargs.get("auth"))

    def test_backoff_preserves_dependency_error_and_heartbeat(self) -> None:
        c.save("test", state="failed")
        with patch.object(c, "github", side_effect=RuntimeError("external API unavailable")):
            c.run_once()
            c.run_once()
        self.assertEqual(c.STATUS["error"], "RuntimeError")
        self.assertGreater(c.STATUS["last_tick"], 0)
        c.NEXT_IDLE_CHECK = 0
        with patch.object(c, "github", side_effect=[[], {"sha": "b" * 40}]):
            c.run_once()
        self.assertEqual(c.STATUS["error"], "")

    def test_api_error_does_not_fail_process_health(self) -> None:
        import threading, urllib.request, urllib.error, time

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
            self.assertEqual(status("/livez"), 200)
            self.assertEqual(status("/healthz"), 200)
            self.assertEqual(status("/dependencies"), 503)
            c.STATUS["last_tick"] = time.time() - 181
            self.assertEqual(status("/livez"), 503)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            c.STATUS.clear()
            c.STATUS.update(saved)

    def test_persisted_queued_run_resumes(self) -> None:
        c.save("test", state="queued")
        with patch.object(c, "start_job") as start:
            c.tick()
            self.assertEqual(start.call_args.args[1], "work")

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
                self.assertEqual(json.loads(handler.wfile.getvalue())["error"], error)


if __name__ == "__main__":
    unittest.main()
