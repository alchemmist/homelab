import argparse
import importlib.metadata
import json
import os
import pathlib
import signal
import time
from typing import cast

from fixtures import check_verdict, fixture_files, task_prompt, verifier_command, seal_execution
from sandbox import Sandbox


def exception_chain(error):
    chain = []
    seen = set()
    current = error
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        chain.append({"type": type(current).__name__, "message": str(current)[:500]})
        nxt = current.__cause__
        if nxt is None:
            for attr in ("original_exception", "cause", "error"):
                candidate = getattr(current, attr, None)
                if isinstance(candidate, BaseException):
                    nxt = candidate
                    break
        if nxt is None and current.__context__ is not None and not current.__suppress_context__:
            nxt = current.__context__
        current = nxt
    return chain


def record_exception(summary, error, key, prefix):
    chain = exception_chain(error)
    redacted = []
    for item in chain:
        message = (
            item["message"].replace(key, "[redacted]")[:2000] if key else item["message"][:2000]
        )
        redacted.append({"type": item["type"], "message": message})
    summary[prefix + "_type"] = redacted[0]["type"]
    summary[prefix] = redacted[0]["message"]
    summary[prefix + "_chain"] = redacted
    if prefix == "run_error":
        summary["error_chain"] = redacted
        if len(redacted) > 1:
            summary["cause_type"] = redacted[1]["type"]
    return redacted


def resolved_mini_exit(result, directory):
    status = result.get("exit_status") if isinstance(result, dict) else None
    if isinstance(status, str) and status:
        return status, "agent_result.exit_status"
    path = directory / "trajectory.json"
    if path.is_symlink() or not path.is_file():
        return None, "unknown"
    from controller import resolve_mini_exit

    return resolve_mini_exit(json.loads(path.read_text()))


def provider_settings():
    source = pathlib.Path(
        os.environ.get("LAB_PI_MODELS", str(pathlib.Path.home() / ".pi/agent/models.json"))
    )
    provider = json.loads(source.read_text())["providers"]["litellm"]
    reference = provider["apiKey"]
    if not reference.startswith("$"):
        raise ValueError("only an environment-backed API key is supported")
    key = os.environ.get(reference.lstrip("$").strip("{}"), "").strip()
    if not key or "\r" in key or "\n" in key:
        raise ValueError("missing or unsafe API key")
    return provider["baseUrl"], key


def mini_submission(result):
    lines = result.get("output", "").lstrip().splitlines()
    return (
        result.get("returncode") == 0
        and bool(lines)
        and lines[0].strip() == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    )


def run_mini(engine, sandbox, directory, prompt, base_url, key):
    os.environ["MSWEA_GLOBAL_CONFIG_DIR"] = str(directory / "mini-config")
    os.environ["MSWEA_SILENT_STARTUP"] = "1"
    os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] = "1"
    os.environ["OPENAI_API_KEY"] = key
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.exceptions import Submitted
    from minisweagent.models.litellm_model import LitellmModel
    from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel

    model_class = LitellmTextbasedModel if engine == "mini_text" else LitellmModel
    model = model_class(
        model_name="openai/v-deepseek-uc",
        cost_tracking="ignore_errors",
        model_kwargs={
            "api_base": base_url,
            "timeout": 720,
            "max_retries": 0,
            "parallel_tool_calls": False,
        },
    )
    query = model._query
    calls = []

    def observed_query(messages, **kwargs) -> object:
        record = {"attempt": len(calls) + 1, "started": time.time()}
        calls.append(record)
        try:
            response = query(messages, **kwargs)
            record.update(
                {
                    "content": response.choices[0].message.content,
                    "tool_calls": [
                        tool.model_dump() for tool in (response.choices[0].message.tool_calls or [])
                    ],
                    "finish_reason": response.choices[0].finish_reason,
                }
            )
            return cast("object", response)
        except Exception as error:
            record["error_type"] = type(error).__name__
            raise
        finally:
            record["elapsed"] = time.time() - record["started"]
            (directory / "model-responses.json").write_text(json.dumps(calls, indent=2))

    model._query = observed_query
    execute = sandbox.execute

    def execute_with_submission(action, **kwargs) -> object:
        result = execute(action, **kwargs)
        if mini_submission(result):
            raise Submitted(
                {
                    "role": "exit",
                    "content": "Submitted",
                    "extra": {"exit_status": "Submitted", "submission": result["output"]},
                }
            )
        return cast("object", result)

    sandbox.execute = execute_with_submission
    system = "You are a coding agent in an isolated offline Linux workspace. "
    if engine == "mini_text":
        system += (
            "Every response must contain exactly one bash action in a fenced block labelled "
            "mswea_bash_command. An optional brief action summary is allowed. Do not provide private reasoning. "
            "Never output more than one command block."
        )
    else:
        system += (
            "Use the declared bash tool for actual actions. Do not merely describe future work."
        )
    agent = DefaultAgent(
        model,
        sandbox,
        system_template=system,
        instance_template="{{task}}",
        step_limit=18,
        cost_limit=0,
        wall_time_limit_seconds=600,
        max_consecutive_format_errors=2,
        output_path=directory / "trajectory.json",
    )
    result = agent.run(prompt)
    status, provenance = resolved_mini_exit(result, directory)
    return {
        "exit_status": status,
        "exit_provenance": provenance,
        "api_attempts": len(calls),
        "package": "mini-swe-agent",
        "version": importlib.metadata.version("mini-swe-agent"),
    }


def continue_openhands(conversation, sandbox, directory, acceptance=None):
    limit = 3 if acceptance is not None else 1
    for round_number in range(limit):
        conversation.run()
        if acceptance is None:
            return "completed"
        facts = acceptance(sandbox, directory, round_number)
        if facts.get("continue") is not True:
            return "stopped"
        if round_number + 1 >= limit:
            return "exhausted"
        conversation.send_message(
            "Independent acceptance rejected this completed response. "
            "Continue in this same conversation from the actual files. "
            "No transport request is replayed. Receipt: " + json.dumps(facts)
        )
    return "completed"


def run_openhands(
    sandbox, directory, prompt, base_url, key, acceptance=None, max_iterations=18, language="Node"
):
    for name in list(os.environ):
        if name.startswith(("LMNR_", "OTEL_", "OPENHANDS_")):
            os.environ.pop(name)
    os.environ["OH_PERSISTENCE_DIR"] = str(directory / "openhands-home")
    os.environ["OTEL_SDK_DISABLED"] = "true"
    from pydantic import Field, SecretStr
    from openhands.sdk import Agent, Conversation, LLM, Tool
    from openhands.sdk.tool import Action, Observation, ToolDefinition, ToolExecutor, register_tool

    class BashAction(Action):
        command: str = Field(
            description="One bash command to execute in the isolated /workspace. Maximum runtime 40 seconds."
        )

    class BashObservation(Observation):
        pass

    class BashExecutor(ToolExecutor):
        def __call__(self, action, _conversation=None) -> BashObservation:
            result = sandbox.execute({"command": action.command})
            return cast(
                "BashObservation",
                BashObservation.from_text(json.dumps(result), is_error=result["returncode"] != 0),
            )

    class BashTool(ToolDefinition[BashAction, BashObservation]):
        name = "bash"

        @classmethod
        def create(cls, conv_state: object = None, **kwargs: object) -> "list[BashTool]":
            return [
                cls(
                    description="Execute bash inside the isolated offline coding workspace. "
                    + language
                    + " and standard Linux tools are available. No host filesystem access.",
                    action_type=BashAction,
                    observation_type=BashObservation,
                    executor=BashExecutor(),
                )
            ]

    register_tool(BashTool.name, BashTool)
    llm = LLM(
        model="openai/v-deepseek-uc",
        base_url=base_url,
        api_key=SecretStr(key),
        native_tool_calling=True,
        num_retries=0,
        timeout=720,
        stream=False,
        max_input_tokens=24000,
        max_output_tokens=6000,
        log_completions=False,
    )
    agent = Agent(llm=llm, tools=[Tool(name=BashTool.name)])
    workspace = directory / "controller-workspace"
    workspace.mkdir()

    def observe(event) -> None:
        with (directory / "openhands-events.jsonl").open("a") as stream:
            stream.write(json.dumps(event.model_dump(mode="json")) + "\n")

    conversation = Conversation(
        agent=agent,
        workspace=str(workspace),
        persistence_dir=str(directory / "conversation"),
        callbacks=[observe],
        visualizer=None,
        max_iteration_per_run=max_iterations,
        delete_on_close=False,
    )
    try:
        conversation.send_message(prompt)
        continuation = continue_openhands(conversation, sandbox, directory, acceptance)
        status = str(conversation.state.execution_status)
    finally:
        conversation.close()
    return {
        "exit_status": status,
        "exit_provenance": "conversation.state.execution_status",
        "continuation": continuation,
        "package": "openhands-sdk",
        "version": importlib.metadata.version("openhands-sdk"),
    }


def attempt(engine, task, directory, seed, feedback=""):
    os.umask(0o077)
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    base_url, key = provider_settings()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    started = time.time()
    summary = {"engine": engine, "task": task, "seed": seed, "accepted": False}
    files = fixture_files(task)
    try:
        with Sandbox(files, directory / "agent") as sandbox:
            try:
                prompt = task_prompt(task)
                if feedback:
                    prompt += (
                        "\nA previous attempt did not pass independent acceptance: " + feedback
                    )
                if engine.startswith("mini_"):
                    result = run_mini(engine, sandbox, directory, prompt, base_url, key)
                else:
                    result = run_openhands(sandbox, directory, prompt, base_url, key)
                summary.update(result)
            except (Exception, KeyboardInterrupt) as error:
                record_exception(summary, error, key, "run_error")
            summary["actual_commands"] = len(sandbox.events)
            snapshot = sandbox.snapshot()
            summary["test_unchanged"] = snapshot["test.cjs"] == files["test.cjs"]
            (directory / "candidate.json").write_text(json.dumps(snapshot, indent=2))
        with Sandbox(snapshot, directory / "verifier", verifier=True) as verifier:
            command, nonce, cases = verifier_command(task, seed)
            execution = verifier.execute(
                {"command": command}, input_bytes=json.dumps(cases).encode()
            )
            verdict = check_verdict(task, nonce, cases, seal_execution(nonce, execution))
            summary["verdict"] = verdict
            summary["accepted"] = verdict["accepted"] and summary["test_unchanged"]
    except (Exception, KeyboardInterrupt) as error:
        record_exception(summary, error, key, "infrastructure_error")
    summary["elapsed_seconds"] = round(time.time() - started, 3)
    (directory / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engine", choices=["mini_native", "mini_text", "openhands"], required=True
    )
    parser.add_argument("--task", choices=["median", "clamp", "escape_html"], required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--feedback", default="")
    args = parser.parse_args()
    attempt(args.engine, args.task, args.directory, args.seed, args.feedback)
