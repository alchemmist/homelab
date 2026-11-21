import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class ControllerFaultTests(unittest.TestCase):
    """Tests for controller behaviour under injected faults."""

    def setup_case(self, directory, behavior):
        root = pathlib.Path(directory)
        code = root / "code"
        code.mkdir()
        for name in ("controller.py", "owned_resources.py"):
            shutil.copy(pathlib.Path(__file__).with_name(name), code / name)
        for name in ("fixtures.py", "sandbox.py"):
            (code / name).write_text("")
        fake = """import argparse,json,pathlib,sys,time
p=argparse.ArgumentParser();p.add_argument('--directory');p.add_argument('--task',default='');
a,rest=p.parse_known_args()
d=pathlib.Path(a.directory);d.mkdir(parents=True)
"""
        if behavior == "restart":
            fake += "marker=pathlib.Path(__file__).with_name('once');\nif not marker.exists():\n marker.write_text('started');time.sleep(600)\n"
            fake += "(d/'summary.json').write_text(json.dumps({'accepted':False,'run_error_type':'APITimeoutError'}))\n"
        elif behavior == "premature_final":
            fake += "(d/'summary.json').write_text(json.dumps({'accepted':False,'exit_status':'stop','actual_commands':0}))\n"
        elif behavior == "malformed_summary":
            fake += "(d/'summary.json').write_text('{broken');sys.exit(7)\n"
        elif behavior == "bad_gateway":
            fake += "accepted=str(d).endswith('attempt-2')\n"
            fake += "(d/'summary.json').write_text(json.dumps({'accepted': accepted, 'run_error_type': 'BadGatewayError'}))\n"
        elif behavior == "wrapped_cause":
            fake += "(d/'summary.json').write_text(json.dumps({'accepted': False, 'run_error_type': 'SDKError', 'cause_type': 'BadGatewayError', 'run_error': 'SDK wrapped BadGatewayError'}))\n"
        elif behavior == "string_only_wrapper":
            fake += "(d/'summary.json').write_text(json.dumps({'accepted': False, 'run_error_type': 'SDKError', 'run_error': 'SDK wrapped BadGatewayError'}))\n"
        elif behavior == "context_window":
            fake += "(d/'summary.json').write_text(json.dumps({'accepted': False, 'run_error_type': 'ContextWindowExceededError', 'error_chain': [{'type': 'ContextWindowExceededError'}]}))\n"
        elif behavior == "bad_request":
            fake += "(d/'summary.json').write_text(json.dumps({'accepted': False, 'run_error_type': 'BadRequestError', 'error_chain': [{'type': 'BadRequestError'}]}))\n"
        elif behavior == "message_context":
            fake += "(d/'summary.json').write_text(json.dumps({'accepted': False, 'run_error_type': 'SDKError', 'run_error': 'context_length_exceeded'}))\n"
        (code / "attempt.py").write_text(fake)
        result = root / "private-state"
        return result, [
            sys.executable,
            str(code / "controller.py"),
            "--root",
            str(result),
            "--mini-python",
            sys.executable,
            "--openhands-python",
            sys.executable,
            "--duration-seconds",
            "30",
            "--rounds",
            "1",
        ]

    def test_model_final_is_not_verified_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, "premature_final")
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=15)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["phase"], "queue_finished")
            self.assertTrue(all(task["status"] == "blocked" for task in state["tasks"]))
            self.assertTrue(all(len(task["attempts"]) == 2 for task in state["tasks"]))

    def test_malformed_summaries_are_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, "malformed_summary")
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=15)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["phase"], "runner_infrastructure_error")
            attempts = [attempt for task in state["tasks"] for attempt in task["attempts"]]
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0]["controller_error"], "missing_or_invalid_summary")
            self.assertFalse(any(task["status"] == "accepted" for task in state["tasks"]))

    def test_kill_resume_preserves_deadline_and_stops_after_repeated_provider_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, "restart")
            original = subprocess.Popen(command, stdout=subprocess.DEVNULL)
            restarted = None
            try:
                for _ in range(100):
                    if (root / "state.json").exists():
                        state = json.loads((root / "state.json").read_text())
                        if state.get("running"):
                            break
                    time.sleep(0.05)
                else:
                    self.fail("controller did not checkpoint its running child")
                child = state["running"]["pid"]
                deadline = state["deadline"]
                signature = state["running"].get("signature")
                self.assertIsInstance(signature, list)
                self.assertEqual(len(signature), 2)
                self.assertIn(f"--directory {state['running']['directory']}", signature[1])
                self.assertNotIn(state["running"]["directory"] + "-other", signature[1])
                original.kill()
                original.wait(timeout=5)
                time.sleep(0.2)
                restart_command = command.copy()
                restart_command[restart_command.index("--duration-seconds") + 1] = "7000"
                restarted = subprocess.Popen(restart_command, stdout=subprocess.DEVNULL)
                restarted.wait(timeout=15)
                state = json.loads((root / "state.json").read_text())
                self.assertEqual(state["deadline"], deadline)
                self.assertEqual(state["phase"], "repeated_provider_failures")
                self.assertEqual(state["controller_restarts"], 1)
                self.assertEqual(
                    state["tasks"][0]["attempts"][0]["controller_error"], "interrupted_attempt"
                )
                self.assertFalse(any(task["status"] == "accepted" for task in state["tasks"]))
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    pass
                else:
                    self.fail("interrupted child is still alive")
            finally:
                for process in (original, restarted):
                    if process and process.poll() is None:
                        process.kill()
                        process.wait()

    def test_bad_gateway_stops_without_resetting_for_an_accepted_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, "bad_gateway")
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=20)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["phase"], "repeated_provider_failures")
            self.assertEqual(state["consecutive_provider_failures"], 2)
            attempts = [attempt for task in state["tasks"] for attempt in task["attempts"]]
            self.assertEqual(len(attempts), 2)
            self.assertTrue(attempts[1]["accepted"])
            self.assertEqual(state["tasks"][0]["status"], "accepted")
            report = (root / "REPORT.md").read_text()
            self.assertIn("Phase: `repeated_provider_failures`", report)
            self.assertIn(repr(state["deadline"]), report)
            self.assertEqual(report, report)  # written once in finally; content stable
            again = report
            from controller import render_report

            self.assertEqual(render_report(state), again)

    def test_structured_cause_is_provider_and_message_text_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, "wrapped_cause")
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=20)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["phase"], "repeated_provider_failures")
            self.assertEqual(len([a for t in state["tasks"] for a in t["attempts"]]), 2)
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, "string_only_wrapper")
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=20)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["phase"], "unknown_error_type")
            self.assertEqual(state["termination_error"], "unknown error type: SDKError")
            self.assertEqual(len([a for t in state["tasks"] for a in t["attempts"]]), 1)
            self.assertIn(
                "Termination error: `unknown error type: SDKError`",
                (root / "REPORT.md").read_text(),
            )

    def test_context_length_and_client_input_are_not_provider_outages(self):
        from controller import classify_result

        self.assertEqual(
            classify_result(
                {
                    "run_error_type": "ContextWindowExceededError",
                    "error_chain": [{"type": "ContextWindowExceededError"}],
                }
            ),
            "context_length",
        )
        self.assertEqual(
            classify_result(
                {"run_error_type": "BadRequestError", "error_chain": [{"type": "BadRequestError"}]}
            ),
            "client_input",
        )
        with self.assertRaises(ValueError):
            classify_result({"run_error_type": "SDKError", "run_error": "context_length_exceeded"})
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, "context_window")
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=20)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["phase"], "context_length_exceeded")
            self.assertEqual(state["consecutive_provider_failures"], 0)
            self.assertIn("Phase: `context_length_exceeded`", (root / "REPORT.md").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, "bad_request")
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=20)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["phase"], "client_input_rejected")
            self.assertEqual(state["consecutive_provider_failures"], 0)
        with tempfile.TemporaryDirectory() as directory:
            root, command = self.setup_case(directory, "message_context")
            subprocess.run(command, stdout=subprocess.DEVNULL, check=True, timeout=20)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["phase"], "unknown_error_type")

    def test_null_exit_is_clean_only_from_top_level_submitted_event(self):
        from controller import attempt_facts, render_report

        bare = {"accepted": True, "exit_status": None, "actual_commands": 4}
        self.assertFalse(attempt_facts(bare)["clean"])
        self.assertEqual(attempt_facts(bare)["exit_provenance"], "unknown")
        with tempfile.TemporaryDirectory() as directory:
            trajectory = pathlib.Path(directory) / "trajectory.json"
            trajectory.write_text(
                json.dumps(
                    {
                        "info": {"exit_status": ""},
                        "messages": [
                            {"role": "exit", "content": "done", "exit_status": "Submitted"}
                        ],
                    }
                )
            )
            recorded = {
                "accepted": True,
                "exit_status": None,
                "actual_commands": 4,
                "directory": directory,
            }
            facts = attempt_facts(recorded)
            self.assertTrue(facts["clean"])
            self.assertEqual(facts["exit_status"], "Submitted")
            self.assertEqual(facts["exit_provenance"], "trajectory.messages.exit.exit_status")
            state = {
                "phase": "queue_finished",
                "deadline": 1794912949.7775471,
                "controller_restarts": 0,
                "consecutive_provider_failures": 0,
                "tasks": [
                    {
                        "id": "0-mini_native-median",
                        "engine": "mini_native",
                        "status": "accepted",
                        "attempts": [recorded],
                    },
                    {
                        "id": "0-mini_native-clamp",
                        "engine": "mini_native",
                        "status": "accepted",
                        "attempts": [bare],
                    },
                ],
            }
            report = render_report(state)
            self.assertEqual(report, render_report(json.loads(json.dumps(state))))
            self.assertIn("1794912949.7775471", report)
            self.assertIn("| mini_native | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |", report)
            self.assertIn("exit unresolved", report)
            self.assertIn("not counterfactual scores", report)

    def test_historical_receipt_report_matches_audited_counts(self):
        receipt = pathlib.Path(
            "/Users/antonmoss/venice-auth/autonomy-comparison-20261117-123339/state.json"
        )
        if not receipt.is_file():
            self.skipTest("historical comparison receipt is not present")
        from controller import render_report

        original = receipt.read_text()
        state = json.loads(original)
        deadline = state["deadline"]
        report = render_report(state)
        self.assertEqual(receipt.read_text(), original)
        self.assertEqual(report, render_report(state))
        self.assertIn(repr(deadline), report)
        self.assertIn("| mini_native | 7 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 9 | 1 | 61 |", report)
        self.assertIn("| openhands | 8 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 10 | 2 | 29 |", report)
        self.assertIn("| mini_text | 1 | 0 | 1 | 1 | 4 | 1 | 1 | 0 | 0 | 15 | 4 | 27 |", report)
        self.assertIn("summary.run_error text", report)
        self.assertIn("| mini_native | 9 | 0 | 0 | 61 |", report)

    def test_exception_chain_records_cause_not_message_text(self):
        from attempt import exception_chain, record_exception

        class SDKError(Exception):
            pass

        class BadGatewayError(Exception):
            pass

        try:
            try:
                raise BadGatewayError("502")
            except BadGatewayError as inner:
                raise SDKError("wrapper text mentions InternalServerError") from inner
        except SDKError as error:
            summary = {}
            record_exception(summary, error, "", "run_error")
        self.assertEqual(summary["run_error_type"], "SDKError")
        self.assertEqual(summary["cause_type"], "BadGatewayError")
        self.assertEqual(
            [item["type"] for item in summary["error_chain"]], ["SDKError", "BadGatewayError"]
        )
        self.assertNotIn("cause_type", {"run_error_type": "SDKError"})

    def test_default_matrix_is_native_and_openhands_until_text_opt_in(self):
        from controller import DEFAULT_ENGINES, initial_state

        state = initial_state(30, 1)
        self.assertEqual(DEFAULT_ENGINES, ("mini_native", "openhands"))
        self.assertEqual(
            [task["engine"] for task in state["tasks"][:2]], ["mini_native", "openhands"]
        )
        self.assertNotIn("mini_text", {task["engine"] for task in state["tasks"]})
        included = initial_state(30, 1, ("mini_native", "openhands", "mini_text"))
        self.assertEqual(
            [task["engine"] for task in included["tasks"][:3]],
            ["mini_native", "openhands", "mini_text"],
        )

    def test_sigkill_rechecks_exact_child_identity(self):
        import controller

        calls = []
        directory = "/tmp/run-a"
        attempt = str(pathlib.Path(controller.__file__).with_name("attempt.py"))
        command = f"{attempt} --directory {directory}"
        snapshots = iter(
            [
                ("Mon Nov 17 12:00:00 2026", command),
                ("Mon Nov 17 12:00:00 2026", command),
                ("Mon Nov 17 12:00:05 2026", command),
            ]
        )
        original = (
            controller.process_signature,
            controller.os.getpgid,
            controller.os.killpg,
            controller.time.sleep,
            controller.cleanup_role,
        )
        controller.process_signature = lambda pid: next(snapshots)
        controller.os.getpgid = lambda pid: pid
        controller.os.killpg = lambda pid, sig: calls.append(sig)
        controller.time.sleep = lambda *_: None
        controller.cleanup_role = lambda root: None
        try:
            controller.cleanup_interrupted(
                {
                    "pid": 424242,
                    "directory": directory,
                    "signature": ["Mon Nov 17 12:00:00 2026", command],
                }
            )
        finally:
            (
                controller.process_signature,
                controller.os.getpgid,
                controller.os.killpg,
                controller.time.sleep,
                controller.cleanup_role,
            ) = original
        self.assertEqual(calls, [signal.SIGTERM])

    def test_cleanup_requires_per_run_ownership_and_collects_both_roles(self):
        import controller

        with tempfile.TemporaryDirectory() as directory:
            run = pathlib.Path(directory) / "run"
            owned = {}
            for role, bad in (("agent", True), ("verifier", False)):
                role_dir = run / role
                role_dir.mkdir(parents=True)
                (role_dir / "container-id").write_text("cid-" + role)
                (role_dir / "volume-name").write_text("venice-lab-" + role)
                owned[role] = str(role_dir.resolve())
            calls = []

            def fake_run(
                args,
                capture_output=None,
                text=None,
                timeout=None,
                check=False,
                stdout=None,
                stderr=None,
            ):
                calls.append(list(args))

                class Result:
                    returncode = 0
                    stdout = ""

                if args[:2] == ["docker", "inspect"]:
                    role = "agent" if args[2].endswith("agent") else "verifier"
                    labels = {"venice-autonomy-lab": "true"}
                    if role == "verifier":
                        labels["venice-autonomy-run"] = owned["verifier"]
                    Result.stdout = json.dumps(
                        [{"Config": {"Labels": labels}, "Name": "/venice-lab-" + role}]
                    )
                    return Result()
                if args[:3] == ["docker", "volume", "inspect"]:
                    Result.stdout = json.dumps(
                        [
                            {
                                "Labels": {
                                    "venice-autonomy-lab": "true",
                                    "venice-autonomy-run": owned["verifier"],
                                }
                            }
                        ]
                    )
                    return Result()
                if args[:3] == ["docker", "volume", "rm"]:
                    raise subprocess.CalledProcessError(1, args)
                return Result()

            import owned_resources

            original_run = owned_resources.subprocess.run
            original_signature = controller.process_signature
            owned_resources.subprocess.run = fake_run
            controller.process_signature = lambda pid: (_ for _ in ()).throw(
                subprocess.CalledProcessError(1, ["ps"])
            )
            try:
                with self.assertRaises(ValueError) as caught:
                    controller.cleanup_interrupted({"pid": 424242, "directory": str(run)})
            finally:
                owned_resources.subprocess.run = original_run
                controller.process_signature = original_signature
            message = str(caught.exception)
            self.assertIn("agent:", message)
            self.assertIn("verifier:", message)
            self.assertFalse(
                any(
                    call[:3] == ["docker", "rm", "-f"] and call[-1] == "cid-agent" for call in calls
                )
            )
            self.assertTrue(
                any(
                    call[:3] == ["docker", "rm", "-f"] and call[-1] == "cid-verifier"
                    for call in calls
                )
            )
            self.assertFalse(
                any(
                    call[:3] == ["docker", "volume", "rm"] and call[-1] == "venice-lab-agent"
                    for call in calls
                )
            )
            self.assertTrue(
                any(
                    call[:3] == ["docker", "volume", "rm"] and call[-1] == "venice-lab-verifier"
                    for call in calls
                )
            )

    def test_same_child_rejects_directory_prefix(self):
        import controller

        directory = "/tmp/run"
        attempt = str(pathlib.Path(controller.__file__).with_name("attempt.py"))
        foreign = f"{attempt} --engine mini_native --directory /tmp/run-other --seed 1"
        exact = f"{attempt} --engine mini_native --directory {directory} --seed 1"
        original_signature = controller.process_signature
        original_getpgid = controller.os.getpgid
        controller.os.getpgid = lambda pid: pid
        try:
            controller.process_signature = lambda pid: ("Mon Nov 17 12:00:00 2026", foreign)
            self.assertFalse(
                controller.same_child(424242, directory, ("Mon Nov 17 12:00:00 2026", foreign))
            )
            controller.process_signature = lambda pid: ("Mon Nov 17 12:00:00 2026", exact)
            self.assertTrue(
                controller.same_child(424242, directory, ("Mon Nov 17 12:00:00 2026", exact))
            )
        finally:
            controller.process_signature = original_signature
            controller.os.getpgid = original_getpgid

    def test_pid_kill_requires_recorded_start_signature(self):
        import controller

        calls = []
        directory = "/tmp/run"
        attempt = str(pathlib.Path(controller.__file__).with_name("attempt.py"))
        command = f"{attempt} --directory {directory}"
        original = (
            controller.process_signature,
            controller.os.getpgid,
            controller.os.killpg,
            controller.time.sleep,
            controller.cleanup_role,
        )
        controller.process_signature = lambda pid: ("Mon Nov 17 12:00:00 2026", command)
        controller.os.getpgid = lambda pid: pid
        controller.os.killpg = lambda pid, sig: calls.append(sig)
        controller.time.sleep = lambda *_: None
        controller.cleanup_role = lambda root: None
        try:
            controller.cleanup_interrupted({"pid": 424242, "directory": directory})
        finally:
            (
                controller.process_signature,
                controller.os.getpgid,
                controller.os.killpg,
                controller.time.sleep,
                controller.cleanup_role,
            ) = original
        self.assertEqual(calls, [])

    def test_cleanup_is_idempotent_for_already_removed_resources(self):
        import controller

        with tempfile.TemporaryDirectory() as directory:
            run = pathlib.Path(directory) / "run"
            owned = {}
            for role in ("agent", "verifier"):
                role_dir = run / role
                role_dir.mkdir(parents=True)
                (role_dir / "container-id").write_text("cid-" + role)
                (role_dir / "volume-name").write_text("venice-lab-" + role)
                owned[role] = str(role_dir.resolve())
            calls = []

            def fake_run(
                args,
                capture_output=None,
                text=None,
                timeout=None,
                check=False,
                stdout=None,
                stderr=None,
            ):
                calls.append(list(args))

                class Result:
                    returncode = 1
                    stdout = ""
                    stderr = "Error: No such object: missing"

                if (
                    args[:3] == ["docker", "volume", "inspect"]
                    and args[-1] == "venice-lab-verifier"
                ):
                    Result.returncode = 0
                    Result.stderr = ""
                    Result.stdout = json.dumps(
                        [
                            {
                                "Labels": {
                                    "venice-autonomy-lab": "true",
                                    "venice-autonomy-run": owned["verifier"],
                                }
                            }
                        ]
                    )
                elif args[:2] == ["docker", "inspect"] and args[2] == "cid-agent":
                    Result.returncode = 0
                    Result.stderr = ""
                    Result.stdout = json.dumps(
                        [
                            {
                                "Config": {
                                    "Labels": {
                                        "venice-autonomy-lab": "true",
                                        "venice-autonomy-run": owned["agent"],
                                    }
                                },
                                "Name": "/venice-lab-agent",
                            }
                        ]
                    )
                elif args[:3] == ["docker", "volume", "rm"] or args[:3] == ["docker", "rm", "-f"]:
                    Result.returncode = 0
                    Result.stderr = ""
                return Result()

            import owned_resources

            original_run = owned_resources.subprocess.run
            original_signature = controller.process_signature
            owned_resources.subprocess.run = fake_run
            controller.process_signature = lambda pid: (_ for _ in ()).throw(
                subprocess.CalledProcessError(1, ["ps"])
            )
            try:
                controller.cleanup_interrupted({"pid": 424242, "directory": str(run)})
            finally:
                owned_resources.subprocess.run = original_run
                controller.process_signature = original_signature
            self.assertTrue(
                any(
                    call[:3] == ["docker", "rm", "-f"] and call[-1] == "cid-agent" for call in calls
                )
            )
            self.assertFalse(
                any(
                    call[:3] == ["docker", "rm", "-f"] and call[-1] == "cid-verifier"
                    for call in calls
                )
            )
            self.assertFalse(
                any(
                    call[:3] == ["docker", "volume", "rm"] and call[-1] == "venice-lab-agent"
                    for call in calls
                )
            )
            self.assertTrue(
                any(
                    call[:3] == ["docker", "volume", "rm"] and call[-1] == "venice-lab-verifier"
                    for call in calls
                )
            )

    def test_cleanup_does_not_swallow_daemon_errors(self):
        import controller

        with tempfile.TemporaryDirectory() as directory:
            run = pathlib.Path(directory) / "run"
            for role in ("agent", "verifier"):
                role_dir = run / role
                role_dir.mkdir(parents=True)
                (role_dir / "container-id").write_text("cid-" + role)
                (role_dir / "volume-name").write_text("venice-lab-" + role)
            calls = []

            def fake_run(
                args,
                capture_output=None,
                text=None,
                timeout=None,
                check=False,
                stdout=None,
                stderr=None,
            ):
                calls.append(list(args))

                class Result:
                    returncode = 1
                    stdout = ""
                    stderr = "Cannot connect to the Docker daemon"

                return Result()

            import owned_resources

            original_run = owned_resources.subprocess.run
            original_signature = controller.process_signature
            owned_resources.subprocess.run = fake_run
            controller.process_signature = lambda pid: (_ for _ in ()).throw(
                subprocess.CalledProcessError(1, ["ps"])
            )
            try:
                with self.assertRaises(ValueError) as caught:
                    controller.cleanup_interrupted({"pid": 424242, "directory": str(run)})
            finally:
                owned_resources.subprocess.run = original_run
                controller.process_signature = original_signature
            message = str(caught.exception)
            self.assertIn("agent:", message)
            self.assertIn("verifier:", message)
            self.assertFalse(
                any(
                    call[:3] == ["docker", "rm", "-f"] or call[:3] == ["docker", "volume", "rm"]
                    for call in calls
                )
            )

    def test_sandbox_close_uses_ownership_validation(self):
        import sandbox

        modules = [sandbox]
        try:
            import owned_resources

            modules.append(owned_resources)
        except ImportError:
            owned_resources = None
        box = sandbox.Sandbox.__new__(sandbox.Sandbox)
        box.directory = pathlib.Path("/tmp/run")
        box.container_id = "cid-foreign"
        box.volume_name = "venice-lab-foreign"
        calls = []

        def fake_run(
            args,
            capture_output=None,
            text=None,
            timeout=None,
            check=False,
            stdout=None,
            stderr=None,
        ):
            calls.append(list(args))

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            if args[:2] == ["docker", "inspect"]:
                Result.stdout = json.dumps(
                    [
                        {
                            "Config": {
                                "Labels": {
                                    "venice-autonomy-lab": "true",
                                    "venice-autonomy-run": "/tmp/elsewhere",
                                }
                            },
                            "Name": "/other",
                        }
                    ]
                )
            elif args[:3] == ["docker", "volume", "inspect"]:
                Result.stdout = json.dumps(
                    [
                        {
                            "Labels": {
                                "venice-autonomy-lab": "true",
                                "venice-autonomy-run": "/tmp/elsewhere",
                            }
                        }
                    ]
                )
            return Result()

        originals = [(module, module.subprocess.run) for module in modules]
        for module in modules:
            module.subprocess.run = fake_run
        try:
            with self.assertRaises(ValueError):
                box.close()
        finally:
            for module, original in originals:
                module.subprocess.run = original
        self.assertFalse(
            any(
                call[:2] == ["docker", "rm"] or call[:3] == ["docker", "volume", "rm"]
                for call in calls
            )
        )
        self.assertEqual(box.container_id, "cid-foreign")
        self.assertEqual(box.volume_name, "venice-lab-foreign")

    def test_cleanup_exception_final_report_is_not_running(self):
        import controller

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            root.chmod(0o700)
            running = {
                "task_id": "0-mini_native-median",
                "pid": 424242,
                "directory": "/tmp/run",
                "signature": ["Mon Nov 17 12:00:00 2026", "attempt.py --directory /tmp/run"],
            }
            state = controller.initial_state(30, 1)
            state["running"] = running
            controller.save_state(root / "state.json", state)

            def boom(record):
                raise ValueError("docker daemon refused")

            original = controller.cleanup_interrupted
            controller.cleanup_interrupted = boom
            try:
                with self.assertRaises(ValueError):
                    controller.run(root, sys.executable, sys.executable, 30, 1)
            finally:
                controller.cleanup_interrupted = original
            saved = json.loads((root / "state.json").read_text())
            report = (root / "REPORT.md").read_text()
            self.assertNotEqual(saved["phase"], "running")
            self.assertNotIn("Phase: `running`", report)
            self.assertEqual(saved["running"], running)


class ReportErrorStateTests(unittest.TestCase):
    """Tests for report error-state classification."""

    def test_accepted_artifact_with_any_error_is_not_a_clean_finish(self):
        import controller

        for field, value in (
            ("run_error_type", "BadRequestError"),
            ("run_error_type", "ContextWindowExceededError"),
            ("run_error_type", "UnknownError"),
            ("cleanup_error_type", "ValueError"),
            ("error_chain", [{"type": "UnknownError"}]),
        ):
            with self.subTest(field=field, value=value):
                attempt = {"accepted": True, "exit_status": "finished", field: value}
                facts = controller.attempt_facts(attempt)
                self.assertTrue(facts["artifact"])
                self.assertFalse(facts["clean"])


if __name__ == "__main__":
    unittest.main()
