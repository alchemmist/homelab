"""Unit tests for the repository_runner and attempt decision logic."""
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import repository_runner
import attempt


class FakeEnvironment:
    def __init__(self, snapshot, directory, image, protocol):
        self.container_id = "fake"
        self.events = []
        self.protocol = protocol
        directory.mkdir()

    def snapshot(self, destination):
        shutil.copytree(os.environ["DECISION_CANDIDATE"], destination)

    def close(self):
        self.container_id = None


def passing_verdict():
    return {
        "passed": True,
        "agent_protocol_unchanged": True,
        "allowed_edits": {"allowed": True, "detail": "methods"},
        "graded": True,
        "grade": {"passed": True, "tests": []},
    }


class FinalDecisionTests(unittest.TestCase):
    def run_main(self, verdict, candidate_main, clean=True, cleanup_error=False):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        base = pathlib.Path(root.name)
        snapshot = base / "snapshot"
        agent = snapshot / "agent"
        agent.mkdir(parents=True)
        (agent / "main.py").write_text(
            "class BrowserSession:\n    async def _answer(self):\n        return 1\n"
        )
        (agent / "agent_protocol.py").write_text("protocol = 1\n")
        candidate = base / "candidate"
        candidate.mkdir()
        (candidate / "main.py").write_text(candidate_main)
        (candidate / "agent_protocol.py").write_text("protocol = 1\n")
        env = {
            "AUTONOMY_EXTERNAL_WATCHDOG": "1",
            "AUTONOMY_PROTOCOL_ROOT": str(pathlib.Path(repository_runner.__file__).parent),
            "AUTONOMY_OUTPUT_ROOT": str(base / "out"),
            "AUTONOMY_SNAPSHOT": str(snapshot),
            "AUTONOMY_WORKER_IMAGE": "sha256:test",
            "AUTONOMY_RUN_NONCE": "decisiontest",
            "AUTONOMY_DEADLINE": "9999999999",
            "DECISION_CANDIDATE": str(candidate),
            "OPENHANDS_SUPPRESS_BANNER": "1",
        }
        (base / "out").mkdir()

        class Environment(FakeEnvironment):
            def close(self):
                if cleanup_error:
                    raise RuntimeError("cleanup failed")
                super().close()

        def invoke(*args, **kwargs):
            if not clean:
                raise RuntimeError("provider failed")
            return {"exit_status": "ConversationExecutionStatus.FINISHED"}

        with mock.patch.dict(os.environ, env, clear=False):
            with (
                mock.patch.object(repository_runner, "RepositoryEnvironment", Environment),
                mock.patch.object(repository_runner, "invoke_openhands", invoke),
                mock.patch.object(
                    repository_runner,
                    "load_local",
                    return_value=mock.Mock(
                        provider_settings=lambda: ("https://unit-test.invalid/v1", "unit-test-key"),
                        record_exception=attempt.record_exception,
                    ),
                ),
                mock.patch.object(
                    repository_runner,
                    "load_protocol",
                    return_value=mock.Mock(
                        verify_snapshot=lambda path: {},
                        grade_candidate_container=lambda *args, **kwargs: verdict,
                        PILOT_LABEL="",
                    ),
                ),
                mock.patch.object(repository_runner.signal, "signal"),
                mock.patch.object(repository_runner.signal, "alarm"),
            ):
                code = repository_runner.main([])
        summary_path = next((base / "out").glob("live-*/summary.json"))
        return code, json.loads(summary_path.read_text())

    def test_clean_valid_candidate_is_overall_success(self):
        source = "class BrowserSession:\n    async def _answer(self):\n        return 1\n"
        code, summary = self.run_main(passing_verdict(), source)
        self.assertTrue(summary["accepted"])
        self.assertTrue(summary["clean_finish"])
        self.assertEqual(code, 0)

    def test_comment_violation_is_not_overall_success(self):
        commented = "class BrowserSession:\n    async def _answer(self):\n        # added comment\n        return 1\n"
        with mock.patch.dict(os.environ, {"AUTONOMY_FORCE_CONTINUE_ONCE": "1"}, clear=False):
            code, summary = self.run_main(passing_verdict(), commented)
        self.assertFalse(summary["accepted"])
        self.assertTrue(summary["clean_finish"])
        self.assertNotEqual(code, 0)

    def test_functional_failure_is_not_accepted(self):
        verdict = passing_verdict()
        verdict["passed"] = False
        code, summary = self.run_main(
            verdict, "class BrowserSession:\n    async def _answer(self):\n        return 1\n"
        )
        self.assertFalse(summary["accepted"])
        self.assertNotEqual(code, 0)

    def test_edit_outside_allowed_methods_is_not_accepted(self):
        verdict = passing_verdict()
        verdict["allowed_edits"] = {"allowed": False}
        code, summary = self.run_main(
            verdict, "class BrowserSession:\n    async def _answer(self):\n        return 1\n"
        )
        self.assertFalse(summary["accepted"])
        self.assertNotEqual(code, 0)

    def test_protocol_change_is_not_accepted(self):
        verdict = passing_verdict()
        verdict["agent_protocol_unchanged"] = False
        code, summary = self.run_main(
            verdict, "class BrowserSession:\n    async def _answer(self):\n        return 1\n"
        )
        self.assertFalse(summary["accepted"])
        self.assertNotEqual(code, 0)

    def test_provider_failure_keeps_artifact_separate_from_overall_success(self):
        code, summary = self.run_main(
            passing_verdict(),
            "class BrowserSession:\n    async def _answer(self):\n        return 1\n",
            clean=False,
        )
        self.assertTrue(summary["accepted"])
        self.assertFalse(summary["clean_finish"])
        self.assertEqual(summary["run_error_type"], "RuntimeError")
        self.assertNotEqual(code, 0)

    def test_cleanup_failure_is_not_overall_success(self):
        code, summary = self.run_main(
            passing_verdict(),
            "class BrowserSession:\n    async def _answer(self):\n        return 1\n",
            cleanup_error=True,
        )
        self.assertTrue(summary["accepted"])
        self.assertEqual(summary["cleanup_error_type"], "RuntimeError")
        self.assertNotEqual(code, 0)

    def test_malformed_verdict_fails_closed(self):
        code, summary = self.run_main(
            {"passed": True},
            "class BrowserSession:\n    async def _answer(self):\n        return 1\n",
        )
        self.assertFalse(summary["accepted"])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()


class AcceptanceFeedbackTests(unittest.TestCase):
    def test_rejection_contains_bounded_failure_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            agent = root / "snapshot" / "agent"
            agent.mkdir(parents=True)
            (agent / "main.py").write_text("value = 1\n")
            message = "x" * 10000 + "RuntimeError: Model returned no assistant content"
            verdict = {
                "passed": False,
                "allowed_edits": {
                    "allowed": False,
                    "detail": "signature changed",
                    "expected_signatures": ["async def _answer(self)"],
                },
                "grade": {
                    "tests": [{"test": "typed_failure", "exit_code": 1, "stderr_tail": message}]
                },
            }
            environment = mock.Mock()
            environment.protocol.grade_candidate_container.return_value = verdict
            environment.snapshot.side_effect = lambda path: shutil.copytree(agent, path)
            with (
                mock.patch.dict(
                    os.environ, {"AUTONOMY_SNAPSHOT": str(root / "snapshot")}, clear=False
                ),
                mock.patch.object(repository_runner.subprocess, "run"),
            ):
                facts = repository_runner.sdk_acceptance(environment, root, 0)
            self.assertFalse(facts["accepted"])
            self.assertEqual(facts["verification"]["allowed_edits"], verdict["allowed_edits"])
            receipt = facts["verification"]["tests"][0]["stderr_tail"]
            self.assertIn("Model returned no assistant content", receipt)
            self.assertLessEqual(len(receipt), 1600)


class ResumePromptTests(unittest.TestCase):
    def test_resume_identifies_original_snapshot_as_the_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            agent = root / "agent"
            agent.mkdir()
            (agent / "main.py").write_text(
                'class BrowserSession:\n    async def _answer(self) -> str:\n        return "ok"\n    async def _generate_on_page(self):\n        return "ok"\n'
            )
            with mock.patch.dict(
                os.environ,
                {"AUTONOMY_SOURCE_CANDIDATE": "previous-candidate", "AUTONOMY_SNAPSHOT": str(root)},
            ):
                prompt = repository_runner.task_prompt()
            self.assertIn("not the original snapshot", prompt)
            self.assertIn("async def _answer(self) -> str:", prompt)
            self.assertIn("Restore these exact headers", prompt)


class SnapshotRejectionTests(unittest.TestCase):
    def test_archive_policy_rejection_is_actionable_without_becoming_a_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            environment = mock.Mock()
            environment.snapshot_rejections = 0
            environment.snapshot.side_effect = repository_runner.CandidateRejected(
                "unexpected candidate member: 'debug'"
            )
            with (
                mock.patch.dict(os.environ, {"AUTONOMY_SNAPSHOT": temp}),
                mock.patch.object(repository_runner.subprocess, "run"),
            ):
                facts = repository_runner.sdk_acceptance(environment, pathlib.Path(temp), 0)
            self.assertFalse(facts["accepted"])
            self.assertTrue(facts["continue"])
            self.assertIn("debug", facts["verification"]["snapshot_error"])
            environment.protocol.grade_candidate_container.assert_not_called()
