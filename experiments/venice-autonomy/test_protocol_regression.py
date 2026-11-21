import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import protocol_regression as pilot


def repo_path():
    return Path(os.environ["PROTOCOL_REGRESSION_REPO"])


def python_path():
    raw = os.environ.get("PROTOCOL_REGRESSION_PYTHON")
    return Path(raw) if raw else Path(sys.executable)


class MethodSignatureTests(unittest.TestCase):
    """Tests that method signature changes are caught."""

    baseline = "class BrowserSession:\n    async def _answer(self, page, fallback=None) -> str:\n        return 'answer'\n    async def _generate_on_page(self, page):\n        return page\n"

    def test_signature_changes_are_rejected(self):
        changes = [
            ("self, page,", "self, injected_parameter, page,"),
            ("fallback=None", "fallback=42"),
            ("-> str", "-> int"),
            ("self, page,", "self, page: str,"),
        ]
        for old, new in changes:
            with self.subTest(new=new):
                report = pilot.allowed_edit_report(self.baseline, self.baseline.replace(old, new))
                self.assertFalse(report["allowed"], report)
                self.assertIn("method signature", report["detail"])
                self.assertTrue(any("_answer" in value for value in report["expected_signatures"]))

    def test_body_changes_remain_allowed(self):
        report = pilot.allowed_edit_report(
            self.baseline, self.baseline.replace("return 'answer'", "return 'fixed'")
        )
        self.assertTrue(report["allowed"], report)

    def test_duplicate_allowed_method_is_rejected(self):
        candidate = (
            self.baseline
            + "    async def _answer(self, page, fallback=None) -> str:\n        return 'override'\n"
        )
        self.assertFalse(pilot.allowed_edit_report(self.baseline, candidate)["allowed"])


class TestCompletionTests(unittest.TestCase):
    """Tests for the test completion flow."""

    def grade(self, body):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            grader = root / "grader"
            grader.mkdir()
            methods = "".join(
                "    def " + name.rsplit(".", 1)[1] + "(self):\n        " + body + "\n"
                for name in pilot.SELECTED_TESTS
            )
            (grader / pilot.GRADER_NAME).write_text(
                "import unittest\nclass RecoveryTests(unittest.TestCase):\n" + methods
            )
            return pilot.run_selected_tests(Path(sys.executable), root, grader)

    def test_early_zero_exit_is_not_a_pass(self):
        self.assertFalse(self.grade("__import__('os')._exit(0)")["passed"])

    def test_skipped_tests_are_not_a_pass(self):
        self.assertFalse(self.grade("self.skipTest('not executed')")["passed"])

    def test_executed_successful_tests_pass(self):
        self.assertTrue(self.grade("self.assertEqual(1, 1)")["passed"])


class GraderProcessTests(unittest.TestCase):
    """Tests for bounded grader subprocess output."""

    def test_both_output_channels_are_bounded(self):
        for channel in (1, 2):
            with self.subTest(channel=channel), self.assertRaisesRegex(ValueError, "output limit"):
                pilot.bounded_test_process(
                    [sys.executable, "-c", "import os;os.write(" + str(channel) + ",b'x'*65536)"],
                    limit=1024,
                )

    def test_process_timeout_is_bounded(self):
        with self.assertRaises(TimeoutError):
            pilot.bounded_test_process(
                [sys.executable, "-c", "import time;time.sleep(30)"], timeout=0.1
            )

    def test_failed_docker_start_is_not_overwritten_by_inspect(self):
        created = subprocess.CompletedProcess([], 0, "container", "")
        inspected = subprocess.CompletedProcess([], 0, "0", "")
        failed = subprocess.CompletedProcess([], 1, "", "start failed")
        with (
            mock.patch.object(pilot, "docker_run", side_effect=[created, inspected]),
            mock.patch.object(pilot, "bounded_test_process", return_value=failed),
            mock.patch.object(pilot, "remove_own_container"),
        ):
            result = pilot.run_container("docker", "image", ["python"], [], "/opt/grader")
        self.assertEqual(result["exit_code"], 1)
        self.assertFalse(result["completed"])


class SnapshotTests(unittest.TestCase):
    """Tests for snapshot artifact persistence."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dest = Path(self.temp.name) / "snapshot"
        self.manifest = pilot.export_snapshot(repo_path(), self.dest)

    def tearDown(self):
        self.temp.cleanup()

    def test_export_is_deterministic_and_grader_stays_outside_agent(self):
        again = Path(self.temp.name) / "again"
        second = pilot.export_snapshot(repo_path(), again)
        self.assertEqual(self.manifest["manifest_sha256"], second["manifest_sha256"])
        self.assertEqual(
            (self.dest / "manifest.json").read_bytes(),
            (again / "manifest.json").read_bytes(),
        )
        verified = pilot.verify_snapshot(self.dest)
        self.assertEqual(verified["label"], "historical_regression_exercise")
        self.assertEqual(verified["claim"], "not_fresh_bug_discovery")
        self.assertFalse((self.dest / "agent" / "test_protocol_recovery.py").exists())
        self.assertTrue((self.dest / "grader" / "test_protocol_recovery.py").is_file())
        names = sorted(path.name for path in self.dest.rglob("*") if path.is_file())
        self.assertEqual(
            names,
            ["agent_protocol.py", "main.py", "manifest.json", "test_protocol_recovery.py"],
        )
        self.assertNotIn(".git", names)
        for item in verified["files"]:
            data = (self.dest / item["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])

    def test_verify_rejects_tamper_extra_file_and_grader_inside_agent(self):
        main = self.dest / "agent" / "main.py"
        original = main.read_bytes()
        main.write_bytes(original + b"\n")
        with self.assertRaises(ValueError) as tampered:
            pilot.verify_snapshot(self.dest)
        self.assertIn("hash mismatch", str(tampered.exception))
        main.write_bytes(original)
        extra = self.dest / "agent" / "extra.py"
        extra.write_text("x = 1\n", encoding="utf-8")
        with self.assertRaises(ValueError) as unexpected:
            pilot.verify_snapshot(self.dest)
        self.assertIn("differ from manifest", str(unexpected.exception))
        extra.unlink()
        shutil.copyfile(
            self.dest / "grader" / "test_protocol_recovery.py",
            self.dest / "agent" / "test_protocol_recovery.py",
        )
        with self.assertRaises(ValueError) as embedded:
            pilot.verify_snapshot(self.dest)
        self.assertIn("grader is inside the agent snapshot", str(embedded.exception))

    def test_allowed_method_boundary(self):
        baseline = (self.dest / "agent" / "main.py").read_text(encoding="utf-8")
        spans = pilot.method_spans(baseline)
        lines = baseline.splitlines(keepends=True)
        start, end = spans["_answer"]
        self.assertGreater(end, start)
        lines.insert(end - 1, "        return None\n")
        inside = "".join(lines)
        inside_report = pilot.allowed_edit_report(baseline, inside)
        self.assertTrue(inside_report["allowed"], inside_report)
        outside_report = pilot.allowed_edit_report(baseline, baseline + "\nOUTSIDE = 1\n")
        self.assertFalse(outside_report["allowed"])
        broken = pilot.allowed_edit_report("class BrowserSession:\n    pass\n", baseline)
        self.assertFalse(broken["allowed"])
        python = python_path()
        protocol = Path(self.temp.name) / "protocol"
        shutil.copytree(self.dest / "agent", protocol)
        protocol_text = (protocol / "agent_protocol.py").read_text(encoding="utf-8")
        (protocol / "agent_protocol.py").write_text(
            protocol_text + "\nPROTOCOL_TAMPER = 1\n", encoding="utf-8"
        )
        rejected_protocol = pilot.grade_candidate(python, self.dest, protocol)
        self.assertFalse(rejected_protocol["graded"])
        self.assertFalse(rejected_protocol["passed"])
        self.assertFalse(rejected_protocol["agent_protocol_unchanged"])
        outside = Path(self.temp.name) / "outside"
        shutil.copytree(self.dest / "agent", outside)
        (outside / "main.py").write_text(baseline + "\nOUTSIDE_TAMPER = 1\n", encoding="utf-8")
        rejected = pilot.grade_candidate(python, self.dest, outside)
        self.assertFalse(rejected["graded"])
        self.assertFalse(rejected["passed"])
        self.assertFalse(rejected["allowed_edits"]["allowed"])

    def test_fail_pass_gate_on_persistent_interpreter(self):
        python = python_path()
        baseline = pilot.grade_candidate(python, self.dest, self.dest / "agent")
        self.assertFalse(baseline["passed"])
        self.assertTrue(baseline["graded"])
        self.assertTrue(all(item["exit_code"] != 0 for item in baseline["grade"]["tests"]))
        fixed_dir = Path(self.temp.name) / "fixed"
        pilot.materialize_known_fixed(repo_path(), self.dest, fixed_dir)
        fixed = pilot.grade_candidate(python, self.dest, fixed_dir)
        self.assertTrue(fixed["passed"], json.dumps(fixed, sort_keys=True))
        self.assertTrue(fixed["allowed_edits"]["allowed"])
        commented = Path(self.temp.name) / "commented"
        shutil.copytree(fixed_dir, commented)
        text = (commented / "main.py").read_text(encoding="utf-8")
        start = pilot.method_spans(text)["_answer"][0]
        lines = text.splitlines(keepends=True)
        lines.insert(start, "        # added comment\n")
        (commented / "main.py").write_text("".join(lines), encoding="utf-8")
        graded = pilot.grade_candidate(python, self.dest, commented)
        self.assertTrue(graded["passed"], json.dumps(graded, sort_keys=True))
        from repository_runner import artifact_accepted

        self.assertFalse(artifact_accepted(graded, self.dest, commented))


if __name__ == "__main__":
    unittest.main()
