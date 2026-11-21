"""Controller that schedules and supervises Venice autonomy benchmark attempts."""
import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import shlex
import signal
import subprocess
import time
from typing import TypedDict, cast

import owned_resources

DEFAULT_ENGINES = ("mini_native", "openhands")
ENGINES = DEFAULT_ENGINES + ("mini_text",)
TASKS = ("median", "clamp", "escape_html")
RUNNER_ERRORS = (
    "TypeError",
    "AttributeError",
    "ImportError",
    "ModuleNotFoundError",
    "UndefinedError",
)
PROVIDER_ERRORS = (
    "APIError",
    "APITimeoutError",
    "Timeout",
    "AuthenticationError",
    "PermissionDeniedError",
    "InternalServerError",
    "RateLimitError",
    "NotFoundError",
    "BadGatewayError",
)
CONTEXT_LENGTH_ERRORS = ("ContextWindowExceededError",)
CLIENT_INPUT_ERRORS = (
    "BadRequestError",
    "InvalidRequestError",
    "UnprocessableEntityError",
    "RejectedRequestError",
)
CLEAN_EXIT_STATUSES = ("Submitted", "finished", "ConversationExecutionStatus.FINISHED")
WRAPPER_ERROR_TYPES = ("ConversationRunError", "SDKError")


def exception_types(result):
    names = []

    def add(value) -> None:
        if isinstance(value, str) and value and value not in names:
            names.append(value)

    add(result.get("run_error_type"))
    add(result.get("cause_type"))
    add(result.get("infrastructure_error_type"))
    for key in ("error_chain", "infrastructure_error_chain"):
        chain = result.get(key)
        if not isinstance(chain, list):
            continue
        for item in chain:
            if isinstance(item, str):
                add(item)
            elif isinstance(item, dict):
                add(item.get("type"))
                add(item.get("cause_type"))
    return names


def structured_provider_errors(result):
    return [name for name in exception_types(result) if name in PROVIDER_ERRORS]


def unstructured_provider_errors(result):
    if (
        result.get("cause_type")
        or result.get("error_chain")
        or result.get("infrastructure_error_chain")
    ):
        return []
    if result.get("run_error_type") not in WRAPPER_ERROR_TYPES:
        return []
    text = result.get("run_error")
    if not isinstance(text, str):
        return []
    return [name for name in PROVIDER_ERRORS if f".{name}" in text or text.startswith(name)]


def classify_result(result):
    if result.get("controller_error"):
        return "runner"
    if (
        result.get("infrastructure_error_type") in RUNNER_ERRORS
        or result.get("run_error_type") in RUNNER_ERRORS
    ):
        return "runner"
    names = exception_types(result)
    if any(name in CONTEXT_LENGTH_ERRORS for name in names):
        return "context_length"
    if structured_provider_errors(result):
        return "provider"
    if any(name in CLIENT_INPUT_ERRORS for name in names):
        return "client_input"
    if result.get("infrastructure_error_type"):
        message = "unknown error type: " + str(result.get("infrastructure_error_type"))
        raise ValueError(message)
    if not names:
        return "none"
    if any(name in RUNNER_ERRORS for name in names):
        return "runner"
    message = "unknown error type: " + names[0]
    raise ValueError(message)


def resolve_mini_exit(trajectory):
    if not isinstance(trajectory, dict):
        return None, "absent"
    messages = trajectory.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "exit":
                continue
            status = message.get("exit_status")
            if isinstance(status, str) and status:
                return status, "trajectory.messages.exit.exit_status"
            extra = message.get("extra")
            if (
                isinstance(extra, dict)
                and isinstance(extra.get("exit_status"), str)
                and extra.get("exit_status")
            ):
                return extra["exit_status"], "trajectory.messages.exit.extra.exit_status"
            break
    info = trajectory.get("info")
    if (
        isinstance(info, dict)
        and isinstance(info.get("exit_status"), str)
        and info.get("exit_status")
    ):
        return info["exit_status"], "trajectory.info.exit_status"
    return None, "unknown"


def resolve_attempt_exit(attempt):
    status = attempt.get("exit_status")
    if isinstance(status, str) and status:
        provenance = (
            attempt.get("exit_provenance")
            if isinstance(attempt.get("exit_provenance"), str)
            else "summary.exit_status"
        )
        return status, provenance
    directory = attempt.get("directory")
    if isinstance(directory, str) and directory:
        path = pathlib.Path(directory) / "trajectory.json"
        if path.is_symlink():
            return None, "unknown"
        if path.is_file():
            try:
                return resolve_mini_exit(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError):
                return None, "unknown"
        return None, "absent"
    return None, "unknown"


def attempt_facts(attempt):
    provider = structured_provider_errors(attempt)
    provider_provenance = "structured" if provider else ""
    if not provider:
        provider = unstructured_provider_errors(attempt)
        provider_provenance = "summary.run_error text" if provider else ""
    exit_status, exit_provenance = resolve_attempt_exit(attempt)
    artifact = attempt.get("accepted") is True
    error_fields = (
        "controller_error",
        "run_error_type",
        "run_error",
        "cause_type",
        "error_chain",
        "infrastructure_error_type",
        "infrastructure_error_chain",
        "cleanup_error_type",
        "cleanup_error",
    )
    clean = (
        artifact
        and not provider
        and not any(attempt.get(key) for key in error_fields)
        and exit_status in CLEAN_EXIT_STATUSES
        and exit_provenance != "unknown"
    )
    return {
        "artifact": artifact,
        "clean": clean,
        "provider": provider,
        "provider_provenance": provider_provenance,
        "exit_status": exit_status,
        "exit_provenance": exit_provenance,
        "commands": attempt.get("actual_commands", 0) or 0,
    }


def _artifact_outcome(facts: list[dict[str, object]]) -> str:
    last = facts[-1]
    if last["provider"]:
        return "artifact_and_provider_error"
    if last["exit_status"] == "LimitsExceeded":
        return "artifact_and_limits_exceeded"
    if last["exit_status"] == "RepeatedFormatError":
        return "artifact_and_repeated_format_error"
    if last["clean"]:
        return "artifact_and_clean_finish"
    return "unknown"


def task_outcome(task):
    facts = [attempt_facts(attempt) for attempt in task.get("attempts", [])]
    if not facts:
        return "pending", facts
    if facts[-1]["artifact"]:
        return _artifact_outcome(facts), facts
    if all(item["exit_status"] == "RepeatedFormatError" and not item["provider"] for item in facts):
        return "blocked_both_format_error", facts
    if (
        len(facts) >= 2
        and facts[0]["exit_status"] == "RepeatedFormatError"
        and not facts[0]["provider"]
        and facts[1]["provider"]
    ):
        return "blocked_format_then_provider", facts
    if all(item["provider"] for item in facts):
        return "blocked_both_provider_error", facts
    return "unknown", facts


def save_state(path, state):
    state["updated_at"] = time.time()
    temporary = path.with_suffix(".new")
    with temporary.open("w") as stream:
        json.dump(state, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def initial_state(duration, rounds, engines=DEFAULT_ENGINES):
    selected = tuple(engines)
    if not selected or any(engine not in ENGINES for engine in selected):
        message = "unknown engine selection"
        raise ValueError(message)
    if not 1 <= duration <= 7200 or not 1 <= rounds <= 10:
        message = "experiment must have 1..7200 seconds and 1..10 rounds"
        raise ValueError(message)
    now = time.time()
    tasks = [
        {
            "id": f"{round_number}-{engine}-{task}",
            "engine": engine,
            "task": task,
            "seed": 170100 + round_number,
            "status": "pending",
            "attempts": [],
        }
        for round_number in range(rounds)
        for task in TASKS
        for engine in selected
    ]
    return {
        "schema": 1,
        "created_at": now,
        "deadline": now + duration,
        "phase": "running",
        "tasks": tasks,
        "running": None,
        "consecutive_provider_failures": 0,
        "controller_restarts": 0,
    }


def settle_task(task, result, max_attempts=2):
    task["attempts"].append(result)
    task["status"] = (
        "accepted"
        if result.get("accepted") is True
        else "blocked"
        if len(task["attempts"]) >= max_attempts
        else "pending"
    )
    return task["status"]


def recover_interrupted(state):
    running = state.get("running")
    if running:
        task = next(task for task in state["tasks"] if task["id"] == running["task_id"])
        settle_task(
            task,
            {
                "accepted": False,
                "controller_error": "interrupted_attempt",
                "directory": running["directory"],
            },
        )
        state["running"] = None
    state["controller_restarts"] += 1


def process_signature(pid):
    started = subprocess.check_output(["ps", "-p", str(pid), "-o", "lstart="], text=True).strip()
    command = subprocess.check_output(["ps", "-p", str(pid), "-o", "args="], text=True).strip()
    return started, command


def same_child(pid, directory, signature):
    expected_script = str(pathlib.Path(__file__).with_name("attempt.py"))
    started, command = process_signature(pid)
    if signature != (started, command) or os.getpgid(pid) != pid:
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    values = [
        argv[index + 1]
        for index, token in enumerate(argv)
        if token == "--directory" and index + 1 < len(argv)
    ]
    if expected_script not in argv or values != [directory]:
        return False
    return process_signature(pid) == (started, command)


def cleanup_role(root):
    owned_resources.cleanup_role(root)


def cleanup_interrupted(running):
    directory = str(running["directory"])
    recorded = running.get("signature")
    if (
        isinstance(recorded, (list, tuple))
        and len(recorded) == 2
        and all(isinstance(part, str) for part in recorded)
    ):
        pid = int(running["pid"])
        signature = (recorded[0], recorded[1])
        try:
            if same_child(pid, directory, signature):
                os.killpg(pid, signal.SIGTERM)
                time.sleep(3)
                if same_child(pid, directory, signature):
                    os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, subprocess.CalledProcessError, PermissionError, OSError):
            pass
    errors = []
    for role in ("agent", "verifier"):
        try:
            cleanup_role(pathlib.Path(directory) / role)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f"{role}: {error}")
    if errors:
        message = "cleanup errors: " + "; ".join(errors)
        raise ValueError(message)


def render_report(state):
    rows = ["# Controlled autonomy experiment", "", f"Phase: `{state.get('phase')}`"]
    if "deadline" in state:
        rows.append(f"Deadline: {state['deadline']!r}")
    rows.append(f"Controller restarts: {state.get('controller_restarts', 0)}")
    rows.append(f"Consecutive provider failures: {state.get('consecutive_provider_failures', 0)}")
    if state.get("termination_error"):
        rows.append(f"Termination error: `{state['termination_error']}`")
    rows += [
        "",
        "| Engine | Accepted tasks | Blocked tasks | Pending tasks | Recorded commands |",
        "|---|---:|---:|---:|---:|",
    ]
    tasks = list(state.get("tasks", []))
    unpacked = [(task, *task_outcome(task)) for task in tasks]
    for engine in ENGINES:
        engine_tasks = [task for task in tasks if task.get("engine") == engine]
        counts = [
            sum(task.get("status") == status for task in engine_tasks)
            for status in ("accepted", "blocked", "pending")
        ]
        commands = sum(
            (attempt.get("actual_commands", 0) or 0)
            for task in engine_tasks
            for attempt in task.get("attempts", [])
        )
        rows.append(f"| {engine} | {counts[0]} | {counts[1]} | {counts[2]} | {commands} |")
    labels = (
        "artifact_and_clean_finish",
        "artifact_and_limits_exceeded",
        "artifact_and_provider_error",
        "artifact_and_repeated_format_error",
        "blocked_both_format_error",
        "blocked_format_then_provider",
        "blocked_both_provider_error",
        "pending",
        "unknown",
    )
    rows += [
        "",
        "| Engine | Clean finish | LimitsExceeded artifact | Provider artifact | Format artifact | Blocked format | Blocked format then provider | Blocked provider | Pending | Unknown | Attempts | Provider-error attempts | Commands |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for engine in ENGINES:
        selected = [
            (outcome, facts) for task, outcome, facts in unpacked if task.get("engine") == engine
        ]
        tally = {label: sum(outcome == label for outcome, facts in selected) for label in labels}
        attempts = sum(len(facts) for outcome, facts in selected)
        provider_attempts = sum(
            bool(item["provider"]) for outcome, facts in selected for item in facts
        )
        commands = sum(item["commands"] for outcome, facts in selected for item in facts)
        rows.append(
            f"| {engine} | {tally['artifact_and_clean_finish']} | {tally['artifact_and_limits_exceeded']} | "
            f"{tally['artifact_and_provider_error']} | {tally['artifact_and_repeated_format_error']} | "
            f"{tally['blocked_both_format_error']} | {tally['blocked_format_then_provider']} | "
            f"{tally['blocked_both_provider_error']} | {tally['pending']} | {tally['unknown']} | "
            f"{attempts} | {provider_attempts} | {commands} |"
        )
    rows += [
        "",
        "| Task | Status | Outcome | Artifact accepted | Clean finish | Resolved exit | Exit provenance | Provider errors | Provider provenance | Attempts | Commands |",
        "|---|---|---|---|---|---|---|---|---|---:|---:|",
    ]
    unknown_lines = []
    for task, outcome, facts in unpacked:
        artifact = any(item["artifact"] for item in facts)
        clean = any(item["clean"] for item in facts)
        last = facts[-1] if facts else None
        resolved = "null" if last is None or last["exit_status"] is None else last["exit_status"]
        exit_provenance = "none" if last is None else last["exit_provenance"]
        provider = [] if last is None else last["provider"]
        provider_provenance = "" if last is None else last["provider_provenance"]
        commands = sum(item["commands"] for item in facts)
        rows.append(
            f"| {task.get('id')} | {task.get('status')} | {outcome} | {str(artifact).lower()} | {str(clean).lower()} | "
            f"{resolved} | {exit_provenance} | {','.join(provider)} | {provider_provenance} | {len(facts)} | {commands} |"
        )
        if outcome == "unknown":
            unknown_lines.append(
                f"- {task.get('id')}: outcome unknown; stored attempts preserved in the attempt table"
            )
    rows += [
        "",
        "## Attempt provenance",
        "| Task | Attempt | Stored exit_status | Stored run_error_type | Stored cause_type | Resolved exit | Exit provenance | Provider errors | Provider provenance | Artifact accepted | Clean finish | Commands |",
        "|---|---:|---|---|---|---|---|---|---|---|---|---:|",
    ]
    for task, outcome, facts in unpacked:
        for index, attempt in enumerate(task.get("attempts", []), start=1):
            item = facts[index - 1]
            stored_exit = attempt.get("exit_status")
            stored_exit_text = "null" if stored_exit is None else str(stored_exit)
            resolved = "null" if item["exit_status"] is None else item["exit_status"]
            rows.append(
                f"| {task.get('id')} | {index} | {stored_exit_text} | {attempt.get('run_error_type') or ''} | "
                f"{attempt.get('cause_type') or ''} | {resolved} | {item['exit_provenance']} | {','.join(item['provider'])} | "
                f"{item['provider_provenance']} | {str(item['artifact']).lower()} | {str(item['clean']).lower()} | {item['commands']} |"
            )
            if item["exit_provenance"] == "unknown" or (
                attempt.get("exit_status") in (None, "")
                and item["exit_status"] is None
                and not item["provider"]
            ):
                unknown_lines.append(
                    f"- {task.get('id')} attempt {index}: exit unresolved; stored exit_status={stored_exit_text}; "
                    f"run_error_type={attempt.get('run_error_type') or ''}"
                )
    rows += ["", "## Unknowns"]
    rows.extend(unknown_lines or ["None."])
    rows += [
        "",
        "The first table counts verifier artifact acceptance. Clean finish is separate and requires a resolved Submitted or finished exit without a provider error.",
        "A null summary exit is resolved only from a real top-level mini trajectory exit event. It is not assumed to be Submitted.",
        "Provider errors are structured type, cause_type, or error_chain entries. Historical wrapper text is used only when no structured cause was stored, and that provenance is labeled `summary.run_error text`.",
        "Raw receipts, deadlines, and stored exit_status values are not rewritten. Unknown outcomes stay unknown. These figures are not counterfactual scores.",
        "Acceptance comes from a fresh isolated verifier, never a model-written pass flag.",
        "These are small synthetic coding tasks, not a certification of general bug-finding or overnight reliability.",
        "Private event logs and candidates remain in this directory. There is no automatic commit, push or deploy.",
    ]
    return "\n".join(rows) + "\n"


def write_report(root, state):
    (root / "REPORT.md").write_text(render_report(state))


class ResumePlan(TypedDict):
    """Run plan parameters resumed or freshly initialized by the controller."""

    path: pathlib.Path
    root: pathlib.Path
    duration: int
    rounds: int
    include_text: bool


def _resume_or_init(plan: ResumePlan) -> dict[str, object]:
    path = plan["path"]
    root = plan["root"]
    duration = plan["duration"]
    rounds = plan["rounds"]
    include_text = plan["include_text"]
    if path.exists():
        state = json.loads(path.read_text())
        if state.get("running"):
            try:
                cleanup_interrupted(state["running"])
            except Exception as error:
                state["phase"] = "cleanup_failed"
                state["termination_error"] = str(error)
                save_state(path, state)
                write_report(root, state)
                raise
        recover_interrupted(state)
    else:
        state = initial_state(duration, rounds, ENGINES if include_text else DEFAULT_ENGINES)
    return cast("dict[str, object]", state)


def _validate_source_hashes(state: dict[str, object]) -> None:
    source_hashes = {
        name: hashlib.sha256(pathlib.Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in (
            "attempt.py",
            "sandbox.py",
            "fixtures.py",
            "controller.py",
            "owned_resources.py",
        )
    }
    if state.get("source_hashes", source_hashes) != source_hashes:
        message = "runner source changed; refusing an incomparable resume"
        raise ValueError(message)
    state["source_hashes"] = source_hashes


def _apply_result_kind(state: dict[str, object], kind: str) -> None:
    if kind == "runner":
        state["phase"] = "runner_infrastructure_error"
    elif kind == "provider":
        state["consecutive_provider_failures"] = (
            cast("int", state["consecutive_provider_failures"]) + 1
        )
    elif kind == "context_length":
        state["phase"] = "context_length_exceeded"
    elif kind == "client_input":
        state["phase"] = "client_input_rejected"
    elif kind == "none":
        state["consecutive_provider_failures"] = 0
    if cast("int", state["consecutive_provider_failures"]) >= 2 and state["phase"] == "running":
        state["phase"] = "repeated_provider_failures"


def _read_result(directory: pathlib.Path, process: "subprocess.Popen[bytes]") -> dict[str, object]:
    summary_path = directory / "summary.json"
    try:
        result = json.loads(summary_path.read_text())
        if not isinstance(result, dict) or type(result.get("accepted")) is not bool:
            message = "invalid summary"
            raise ValueError(message)
    except (OSError, ValueError):
        result = {
            "accepted": False,
            "controller_error": "missing_or_invalid_summary",
            "process_exit": process.returncode,
        }
    return result


class TaskRunCtx(TypedDict):
    """Interpreter paths needed to execute one task attempt."""

    root: pathlib.Path
    path: pathlib.Path
    mini_python: str
    openhands_python: str


def _run_one_task(state: dict[str, object], task: dict[str, object], ctx: TaskRunCtx) -> None:
    root, path, mini_python, openhands_python = (
        ctx["root"],
        ctx["path"],
        ctx["mini_python"],
        ctx["openhands_python"],
    )
    attempts = cast("list[dict[str, object]]", task["attempts"])
    task_id = cast("str", task["id"])
    directory = root / "runs" / (task_id + "-attempt-" + str(len(attempts) + 1))
    directory.parent.mkdir(exist_ok=True)
    python = mini_python if cast("str", task["engine"]).startswith("mini_") else openhands_python
    command = [
        python,
        "-u",
        str(pathlib.Path(__file__).with_name("attempt.py")),
        "--engine",
        cast("str", task["engine"]),
        "--task",
        cast("str", task["task"]),
        "--directory",
        str(directory),
        "--seed",
        str(task["seed"]),
    ]
    if attempts:
        command += [
            "--feedback",
            json.dumps(attempts[-1].get("verdict", {"accepted": False}))[:1800],
        ]
    with (root / (task_id + "-" + str(len(attempts) + 1) + ".log")).open("w") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            signature = list(process_signature(process.pid))
        except subprocess.CalledProcessError:
            if process.poll() is None:
                raise
            signature = None
        running: dict[str, object] = {
            "task_id": task_id,
            "pid": process.pid,
            "directory": str(directory),
        }
        if signature:
            running["signature"] = signature
        state["running"] = running
        save_state(path, state)
        try:
            process.wait(
                timeout=max(1, min(900, float(cast("float", state["deadline"])) - time.time()))
            )
        except subprocess.TimeoutExpired:
            try:
                cleanup_interrupted(running)
            except Exception as error:
                state["phase"] = "cleanup_failed"
                state["termination_error"] = str(error)
                raise
            process.wait(timeout=10)
    result = _read_result(directory, process)
    result["directory"] = str(directory)
    settle_task(task, result)
    try:
        kind = classify_result(result)
    except ValueError as error:
        if not str(error).startswith("unknown error type:"):
            raise
        state["phase"] = "unknown_error_type"
        state["termination_error"] = str(error)
        kind = "unknown"
    _apply_result_kind(state, cast("str", kind))
    state["running"] = None
    save_state(path, state)
    write_report(root, state)
    print(
        json.dumps(
            {
                "task": task_id,
                "status": task["status"],
                "accepted": result.get("accepted"),
            }
        ),
        flush=True,
    )


def run(root, mini_python, openhands_python, duration, rounds, include_text=False):
    os.umask(0o077)
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        message = "controller root must be a private real directory"
        raise ValueError(message)
    with (root / "controller.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = root / "state.json"
        plan: ResumePlan = {
            "path": path,
            "root": root,
            "duration": duration,
            "rounds": rounds,
            "include_text": include_text,
        }
        state = _resume_or_init(plan)
        _validate_source_hashes(state)
        save_state(path, state)
        try:
            while time.time() < cast("float", state["deadline"]) and state["phase"] == "running":
                task = next(
                    (
                        task
                        for task in cast("list[dict[str, object]]", state["tasks"])
                        if task["status"] == "pending"
                    ),
                    None,
                )
                if task is None:
                    state["phase"] = "queue_finished"
                    break
                task_run_ctx: TaskRunCtx = {
                    "root": root,
                    "path": path,
                    "mini_python": mini_python,
                    "openhands_python": openhands_python,
                }
                _run_one_task(state, task, task_run_ctx)

            if state["phase"] == "running":
                state["phase"] = "deadline_reached"
        except KeyboardInterrupt:
            if state.get("running"):
                try:
                    cleanup_interrupted(state["running"])
                except Exception as error:
                    state["phase"] = "cleanup_failed"
                    state["termination_error"] = str(error)
                    raise
                recover_interrupted(state)
            state["phase"] = "operator_stopped"
        finally:
            save_state(path, state)
            write_report(root, state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--mini-python", required=True)
    parser.add_argument("--openhands-python", required=True)
    parser.add_argument("--duration-seconds", type=int, default=5400)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument(
        "--include-text",
        action="store_true",
        help="opt in to the mini text-only engine; default matrix is native mini and OpenHands",
    )
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    run(
        args.root,
        args.mini_python,
        args.openhands_python,
        args.duration_seconds,
        args.rounds,
        args.include_text,
    )
