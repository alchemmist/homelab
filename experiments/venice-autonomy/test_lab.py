import io
import json
import subprocess
import tarfile
import unittest
from typing import cast

from fixtures import cases_for, check_verdict, expected
from sandbox import inspect_archive


def archive(entries) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as stream:
        for name, content, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            if kind == tarfile.REGTYPE:
                member.size = len(content)
            else:
                member.linkname = "/Users/owner/.ssh/id_ed25519"
            stream.addfile(member, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
    return buffer.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_regular_files(self) -> None:
        result = inspect_archive(
            archive([("lib.cjs", b"code", tarfile.REGTYPE), ("test.cjs", b"test", tarfile.REGTYPE)])
        )
        self.assertEqual(result, {"lib.cjs": "code", "test.cjs": "test"})

    def test_symlink_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(archive([("lib.cjs", b"", tarfile.SYMTYPE)]))

    def test_hardlink_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(archive([("lib.cjs", b"", tarfile.LNKTYPE)]))

    def test_traversal_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(archive([("../lib.cjs", b"x", tarfile.REGTYPE)]))

    def test_absolute_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(archive([("/lib.cjs", b"x", tarfile.REGTYPE)]))

    def test_oversized_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(archive([("lib.cjs", b"x" * 65537, tarfile.REGTYPE)]))

    def test_duplicate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(archive([("lib.cjs", b"x", tarfile.REGTYPE)] * 2))

    def test_missing_test_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(archive([("lib.cjs", b"x", tarfile.REGTYPE)]))

    def test_extra_file_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(
                archive(
                    [
                        ("lib.cjs", b"x", tarfile.REGTYPE),
                        ("test.cjs", b"x", tarfile.REGTYPE),
                        ("other", b"x", tarfile.REGTYPE),
                    ]
                )
            )

    def test_dot_suffix_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(
                archive(
                    [
                        ("lib.cjs/.", b"code", tarfile.REGTYPE),
                        ("test.cjs", b"test", tarfile.REGTYPE),
                    ]
                )
            )

    def test_nul_smuggled_name_is_rejected(self) -> None:
        blob = bytearray(
            archive([("lib.cjs", b"code", tarfile.REGTYPE), ("test.cjs", b"test", tarfile.REGTYPE)])
        )
        payload = bytes([108, 105, 98, 46, 99, 106, 115, 0]) + b"/../../../../tmp/pwned"
        blob[0 : len(payload)] = payload
        header = bytearray(blob[:512])
        header[148:156] = b"        "
        checksum = sum(header)
        blob[148:155] = format(checksum, "06o").encode("ascii") + bytes([0])
        blob[155:156] = b" "
        with self.assertRaises(ValueError):
            inspect_archive(bytes(blob))

    def test_decode_and_format_errors_are_value_errors(self) -> None:
        with self.assertRaises(ValueError):
            inspect_archive(b"not a tar")
        with self.assertRaises(ValueError):
            inspect_archive(
                archive(
                    [
                        ("lib.cjs", bytes([255]), tarfile.REGTYPE),
                        ("test.cjs", b"t", tarfile.REGTYPE),
                    ]
                )
            )
        short = archive(
            [("lib.cjs", b"code", tarfile.REGTYPE), ("test.cjs", b"test", tarfile.REGTYPE)]
        )[:200]
        with self.assertRaises(ValueError):
            inspect_archive(short)


class VerifierTests(unittest.TestCase):
    def test_expected(self) -> None:
        self.assertEqual(expected("median", [[10, 2, 1]]), {"value": 2})
        self.assertEqual(expected("median", [[1, 2]]), {"value": 1.5})
        self.assertEqual(expected("median", [[]]), {"error": "RangeError"})
        self.assertEqual(expected("clamp", [8, -2, 0]), {"value": 0})
        self.assertEqual(expected("clamp", [1, 2, 0]), {"error": "RangeError"})
        self.assertEqual(expected("escape_html", ["<&'\""]), {"value": "&lt;&amp;&#39;&quot;"})

    def test_zero_exit_without_output_is_not_success(self) -> None:
        self.assertFalse(
            check_verdict("median", "nonce", [[[]]], {"returncode": 0, "output": ""})["accepted"]
        )

    def test_wrong_nonce_is_not_success(self) -> None:
        result = {"returncode": 0, "output": json.dumps({"nonce": "other", "results": []})}
        self.assertFalse(check_verdict("median", "nonce", [], result)["accepted"])

    def test_process_failure_is_not_success(self) -> None:
        result = {"returncode": 1, "output": json.dumps({"nonce": "nonce", "results": []})}
        self.assertFalse(check_verdict("median", "nonce", [], result)["accepted"])

    def test_each_contract_and_mutation(self) -> None:
        for task in ("median", "clamp", "escape_html"):
            cases = cases_for(task, 1234)
            results = [expected(task, args) | {"mutated": False} for args in cases]
            result = {"returncode": 0, "output": json.dumps({"nonce": "nonce", "results": results})}
            self.assertTrue(check_verdict(task, "nonce", cases, result)["accepted"])
            results[0]["mutated"] = True
            result["output"] = json.dumps({"nonce": "nonce", "results": results})
            self.assertFalse(check_verdict(task, "nonce", cases, result)["accepted"])

    def test_deterministic_cases(self) -> None:
        self.assertEqual(cases_for("median", 123), cases_for("median", 123))
        self.assertNotEqual(cases_for("median", 123), cases_for("median", 124))

    def test_loose_types_and_missing_output_fail_closed(self) -> None:
        cases = [[[10, 2, 1]]]
        good = expected("median", cases[0]) | {"mutated": False}
        body = {"nonce": "n", "results": [dict(good)]}
        for flag in (0, 0.0, True):
            payload = json.loads(json.dumps(body))
            payload["results"][0]["mutated"] = flag
            verdict = check_verdict(
                "median", "n", cases, {"returncode": 0, "output": json.dumps(payload)}
            )
            self.assertFalse(verdict["accepted"])
        payload = json.loads(json.dumps(body))
        payload["results"][0]["value"] = True
        self.assertFalse(
            check_verdict("median", "n", cases, {"returncode": 0, "output": json.dumps(payload)})[
                "accepted"
            ]
        )
        self.assertFalse(
            check_verdict("median", "n", cases, {"returncode": False, "output": json.dumps(body)})[
                "accepted"
            ]
        )
        self.assertFalse(
            check_verdict("median", "n", cases, {"returncode": 0.0, "output": json.dumps(body)})[
                "accepted"
            ]
        )
        self.assertFalse(check_verdict("median", "n", cases, {"returncode": 0})["accepted"])
        self.assertFalse(
            check_verdict(
                "median",
                "n",
                cases,
                {"returncode": 0, "output": json.dumps({"nonce": "n", "results": [{}]})},
            )["accepted"]
        )


GOOD = {
    "median": "exports.solve = values => {\n"
    "  if (!Array.isArray(values) || values.length === 0) throw new RangeError('empty');\n"
    "  const a = values.slice().sort((x, y) => x - y);\n"
    "  const n = a.length;\n"
    "  return n % 2 ? a[n >> 1] : (a[n / 2 - 1] + a[n / 2]) / 2;\n"
    "};\n",
    "clamp": "exports.solve = (value, low, high) => {\n"
    "  if (low > high) throw new RangeError('bounds');\n"
    "  return Math.max(low, Math.min(high, value));\n"
    "};\n",
    "escape_html": "exports.solve = text => text\n"
    "  .replace(/&/g, '&amp;')\n"
    "  .replace(/</g, '&lt;')\n"
    "  .replace(/>/g, '&gt;')\n"
    "  .replace(/\"/g, '&quot;')\n"
    "  .replace(/'/g, '&#39;');\n",
}

SPOOF = (
    "exports.solve = values => {\n"
    "  if (!Array.isArray(values) || values.length === 0) throw new RangeError('empty');\n"
    "  const snap = values.slice();\n"
    "  const a = values.sort((x, y) => x - y);\n"
    "  values.toJSON = () => snap;\n"
    "  const n = a.length;\n"
    "  return n % 2 ? a[n >> 1] : (a[n / 2 - 1] + a[n / 2]) / 2;\n"
    "};\n"
)


class NodeVerifierTests(unittest.TestCase):
    def run_source(
        self, task, source, seed=7
    ) -> "tuple[dict[str, object], subprocess.CompletedProcess[str]]":
        import pathlib
        import tempfile
        from fixtures import verifier_command, seal_execution

        command, nonce, cases = verifier_command(task, seed)
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "lib.cjs").write_text(source)
            proc = subprocess.run(
                command,
                shell=True,
                cwd=directory,
                capture_output=True,
                text=True,
                input=json.dumps(cases),
                timeout=15,
            )
        return check_verdict(
            task,
            nonce,
            cases,
            seal_execution(nonce, {"returncode": proc.returncode, "output": proc.stdout}),
        ), proc

    def test_good_solutions_pass(self) -> None:
        for task, source in GOOD.items():
            verdict, proc = self.run_source(task, source)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(verdict["accepted"], verdict)

    def test_tojson_mutation_spoof_is_rejected(self) -> None:
        verdict, proc = self.run_source("median", SPOOF)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(verdict["accepted"])
        self.assertEqual(verdict["reason"], "contract mismatch")

    def test_process_eval_stdout_forgery_is_rejected(self) -> None:
        source = r"""exports.solve = () => 42;
const match = process._eval.match(/const cases=(.*?);const nonce=([^;]+);/s);
const cases = JSON.parse(match[1]);
const nonce = JSON.parse(match[2]);
const results = cases.map(args => {
  const a = args[0].slice().sort((x,y) => x-y);
  if (!a.length) return {error:'RangeError',mutated:false};
  const n = a.length;
  return {value:n%2?a[n>>1]:(a[n/2-1]+a[n/2])/2,mutated:false};
});
process.stdout.write(JSON.stringify({nonce,results}));
process.exit(0);
"""
        verdict, proc = self.run_source("median", source)
        self.assertFalse(verdict["accepted"])

    def test_host_constructor_access_is_blocked(self) -> None:
        for root in ("module", "globalThis"):
            source = (
                "try {const p="
                + root
                + ".constructor.constructor('return process')();p.stdout.write('HOST_ESCAPE_SUCCEEDED');}catch(ignored){} exports.solve=()=>42;"
            )
            verdict, proc = self.run_source("median", source)
            self.assertFalse(verdict["accepted"])
            self.assertNotIn("HOST_ESCAPE_SUCCEEDED", proc.stdout)

    def test_prototype_json_poisoning_cannot_forge_results(self) -> None:
        source = "Object.prototype.toJSON=()=>({value:42,mutated:false}); exports.solve=()=>42;"
        verdict, proc = self.run_source("median", source)
        self.assertFalse(verdict["accepted"])

    def test_exception_getter_is_bounded_in_candidate_realm(self) -> None:
        source = "exports.solve=()=>{throw new Proxy({}, {get(){while(true){}}});};"
        verdict, proc = self.run_source("median", source)
        self.assertFalse(verdict["accepted"])

    def test_restored_input_mutation_is_still_rejected(self) -> None:
        source = "exports.solve=a=>{if(!a.length)throw new RangeError();const v=a[0];a[0]=999;a[0]=v;const b=a.slice().sort((x,y)=>x-y);const n=b.length;return n%2?b[n>>1]:(b[n/2-1]+b[n/2])/2;};"
        verdict, proc = self.run_source("median", source)
        self.assertFalse(verdict["accepted"])


class ControllerTests(unittest.TestCase):
    def test_rejection_retries_then_blocks(self) -> None:
        from controller import settle_task

        task = {"attempts": [], "status": "pending"}
        self.assertEqual(settle_task(task, {"accepted": False}), "pending")
        self.assertEqual(settle_task(task, {"accepted": False}), "blocked")

    def test_only_typed_acceptance_counts(self) -> None:
        from controller import settle_task

        for result in (
            {"accepted": "true"},
            {"model_report": "all tests passed"},
            {"exit_status": "stop"},
        ):
            task = {"attempts": [], "status": "pending"}
            self.assertNotEqual(settle_task(task, result), "accepted")
        task = {"attempts": [], "status": "pending"}
        self.assertEqual(settle_task(task, {"accepted": True}), "accepted")

    def test_restart_preserves_deadline_and_rejects_unfinished_attempt(self) -> None:
        from controller import initial_state, recover_interrupted

        state = initial_state(120, 1)
        deadline = state["deadline"]
        tasks = cast("list[dict[str, object]]", state["tasks"])
        task = tasks[0]
        state["running"] = {"task_id": task["id"], "directory": "/private/test"}
        recover_interrupted(state)
        self.assertEqual(state["deadline"], deadline)
        self.assertEqual(task["status"], "pending")
        attempts = cast("list[dict[str, object]]", task["attempts"])
        self.assertFalse(attempts[0]["accepted"])
        self.assertEqual(attempts[0]["controller_error"], "interrupted_attempt")
        self.assertIsNone(state["running"])

    def test_atomic_checkpoint(self) -> None:
        import pathlib
        import tempfile
        from controller import save_state

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "state.json"
            save_state(path, {"phase": "running"})
            self.assertEqual(json.loads(path.read_text())["phase"], "running")
            self.assertFalse(path.with_suffix(".new").exists())


class MiniAdapterTests(unittest.TestCase):
    def test_completion_uses_executed_output_not_command_spelling(self) -> None:
        from attempt import mini_submission

        marker = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        self.assertTrue(mini_submission({"returncode": 0, "output": marker + "\n"}))
        self.assertTrue(mini_submission({"returncode": 0, "output": "\n" + marker + "\nsummary"}))
        self.assertFalse(mini_submission({"returncode": 1, "output": marker}))
        self.assertFalse(mini_submission({"returncode": 0, "output": "other\n" + marker}))
        self.assertFalse(mini_submission({"returncode": 0, "output": ""}))

    def test_completed_receipt_formats_for_both_action_protocols(self) -> None:
        try:
            from minisweagent.models.litellm_model import LitellmModel
        except ModuleNotFoundError as error:
            self.skipTest(f"mini-swe-agent is not installed: {error}")
        from unittest.mock import patch
        from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel
        from sandbox import Sandbox
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            sandbox = Sandbox.__new__(Sandbox)
            sandbox.directory = pathlib.Path(directory)
            sandbox.events = []
            sandbox.container_id = "isolated-test-double"
            sandbox.verifier = False
            with patch("sandbox.bounded_process", return_value=(0, b"observed\n")):
                output = sandbox.execute({"command": "echo observed"})
            self.assertIsNone(output["exception_info"])
            for model_type in (LitellmModel, LitellmTextbasedModel):
                model = model_type(model_name="openai/v-deepseek-uc", cost_tracking="ignore_errors")
                message = {
                    "extra": {
                        "actions": [{"command": "echo observed", "tool_call_id": "call_fixture"}]
                    }
                }
                messages = model.format_observation_messages(message, [output])
                self.assertIn("observed", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
