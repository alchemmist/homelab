"""Tests for the WebUI tool guard restrictions."""

import importlib.util
import json
import pathlib
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "charts/open-webui/files" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = load("tool_guard")

MAX_ERROR_MESSAGE_CHARS = 600
REPEAT_STOP_EXECUTIONS = 2
ESCALATION_MIN_EXECUTIONS = 4
RECURRENCE_WARN_EXECUTIONS = 3
RECURRENCE_SUFFIX_EXECUTIONS = 4
RECURRENCE_SECOND_WARN_EXECUTIONS = 5
BACKEND_REPEAT_ERROR_CALLS = 3
PATCHER = load("patch_tool_guard")
SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "replacements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["target", "replacement"],
                "properties": {"target": {"type": "string"}, "replacement": {"type": "string"}},
            },
        },
    },
    "required": ["path", "replacements"],
}
BAD = {
    "path": "/tmp/example",
    "replacements": [{"old_text": "PRIVATE CODE", "new_text": "PRIVATE CODE 2"}],
}
GOOD = {"path": "/tmp/example", "replacements": [{"target": "old", "replacement": "new"}]}


class ToolGuardTests(unittest.IsolatedAsyncioTestCase):
    """Tests for ToolGuardTests."""

    def setUp(self):
        self.metadata = {
            "message_id": "one",
            "tools": {"replace_file_content": {"type": "terminal", "spec": {"parameters": SCHEMA}}},
        }
        self.calls = 0
        self.result = {"success": True}

        async def execute(form_data, metadata, event_caller, call):
            self.calls += 1
            return (
                json.loads(call["function"]["arguments"]),
                self.result,
                metadata["tools"]["replace_file_content"],
                "terminal",
                False,
            )

        self.execute = GUARD.guarded_execute(execute)

    async def call(self, params=BAD, raw=None):
        return await self.execute(
            {},
            self.metadata,
            None,
            {
                "function": {
                    "name": "replace_file_content",
                    "arguments": raw if raw is not None else json.dumps(params),
                }
            },
        )

    async def test_nested_validation_is_concise_and_never_executes(self):
        result = await self.call()
        error = result[1]["error"]
        assert "target, replacement" in error
        assert "not executed" in error
        assert "PRIVATE" not in error
        assert self.calls == 0
        assert len(error) < MAX_ERROR_MESSAGE_CHARS

    async def test_third_identical_invalid_call_stops_despite_formatting(self):
        await self.call()
        await self.call(raw=json.dumps(BAD, sort_keys=True, indent=4))
        assert not GUARD.guard_stopped(self.metadata)
        await self.call()
        assert GUARD.guard_stopped(self.metadata)
        result = await self.call(GOOD)
        assert result[1]["error"] == GUARD.STOP_MESSAGE
        assert self.calls == 0

    async def test_valid_calls_are_unchanged(self):
        result = await self.call(GOOD)
        assert result[1] == self.result
        assert self.calls == 1

    async def test_unrelated_success_does_not_hide_same_invalid_call(self):
        await self.call()
        await self.call(GOOD)
        await self.call()
        await self.call(GOOD)
        await self.call()
        assert GUARD.guard_stopped(self.metadata)
        assert self.calls == REPEAT_STOP_EXECUTIONS

    async def test_corrected_arguments_allow_recovery(self):
        await self.call()
        await self.call(GOOD)
        assert self.calls == 1
        assert not GUARD.guard_stopped(self.metadata)

    async def test_identical_valid_calls_warn_then_stop(self):
        await self.call(GOOD)
        await self.call(GOOD)
        warned = await self.call(GOOD)
        assert self.calls == REPEAT_STOP_EXECUTIONS
        assert "not run again" in warned[1]["error"]
        assert not GUARD.guard_stopped(self.metadata)
        stopped = await self.call(GOOD)
        assert GUARD.guard_stopped(self.metadata)
        assert self.calls == REPEAT_STOP_EXECUTIONS
        assert stopped[1]["error"] == GUARD.REPEAT_STOP_MESSAGE
        assert GUARD.guard_stop_message(self.metadata) == GUARD.REPEAT_STOP_MESSAGE

    async def test_alternating_valid_calls_escalate_to_stop(self):
        other = {"path": "/tmp/other", "replacements": [{"target": "x", "replacement": "y"}]}
        executed = 0
        for _ in range(6):
            await self.call(GOOD)
            executed += 1
            if GUARD.guard_stopped(self.metadata):
                break
            await self.call(other)
            executed += 1
            if GUARD.guard_stopped(self.metadata):
                break
        assert GUARD.guard_stopped(self.metadata)
        assert self.calls < executed
        assert self.calls >= ESCALATION_MIN_EXECUTIONS

    async def test_varied_calls_reset_repeat_warning(self):
        other = {"path": "/tmp/other", "replacements": []}
        await self.call(GOOD)
        await self.call(GOOD)
        warned = await self.call(GOOD)
        assert "not run again" in warned[1]["error"]
        assert not GUARD.guard_stopped(self.metadata)
        recovered = await self.call(other)
        assert recovered[1] == self.result
        assert self.calls == RECURRENCE_WARN_EXECUTIONS
        await self.call(GOOD)
        assert self.calls == RECURRENCE_SUFFIX_EXECUTIONS
        await self.call(GOOD)
        assert self.calls == RECURRENCE_SECOND_WARN_EXECUTIONS
        warned_again = await self.call(GOOD)
        assert "not run again" in warned_again[1]["error"]
        assert self.calls == RECURRENCE_SECOND_WARN_EXECUTIONS
        assert not GUARD.guard_stopped(self.metadata)
        stopped = await self.call(GOOD)
        assert GUARD.guard_stopped(self.metadata)
        assert stopped[1]["error"] == GUARD.REPEAT_STOP_MESSAGE

    async def test_alias_resolved_before_validation(self):
        def resolve(call, tools):
            call["function"]["name"] = "replace_file_content"

        with patch.dict(self.execute.__wrapped__.__globals__, {"resolve_tool_call": resolve}):
            result = await self.execute(
                {},
                self.metadata,
                None,
                {"function": {"name": "terminal_replace_alias", "arguments": json.dumps(BAD)}},
            )
        assert "target" in result[1]["error"]
        assert self.calls == 0

    async def test_non_terminal_is_not_intercepted(self):
        self.metadata["tools"]["replace_file_content"]["type"] = "external"
        await self.call()
        assert self.calls == 1

    async def test_next_message_resets_guard(self):
        for _ in range(3):
            await self.call()
        self.metadata["message_id"] = "two"
        await self.call(GOOD)
        assert self.calls == 1
        assert not GUARD.guard_stopped(self.metadata)

    async def test_chats_are_isolated(self):
        for _ in range(3):
            await self.call()
        other = {"message_id": "one", "tools": self.metadata["tools"]}
        assert not GUARD.guard_stopped(other)

    async def test_malformed_json_and_nonobject_safe(self):
        result = await self.call(raw='{"unfinished":')
        assert "complete JSON" in result[1]["error"]
        result = await self.call(raw="[]")
        assert result[0] == {}
        assert self.calls == 0

    async def test_backend_422_compacted_and_bounded(self):
        self.result = ({"error": 'HTTP error 422: {"input":"PRIVATE CODE"}'}, None)
        for _ in range(3):
            result = await self.call(GOOD)
        assert GUARD.guard_stopped(self.metadata)
        assert "PRIVATE" not in result[1]["error"]
        assert self.calls == BACKEND_REPEAT_ERROR_CALLS

    async def test_backend_other_errors_do_not_count(self):
        self.result = {"error": "HTTP error 503: unavailable"}
        first = await self.call(GOOD)
        second = await self.call(GOOD)
        assert first[1] == self.result
        assert second[1] == self.result
        assert not GUARD.guard_stopped(self.metadata)
        assert GUARD.guard_state(self.metadata)["failures"] == {}
        warned = await self.call(GOOD)
        assert "not run again" in warned[1]["error"]
        stopped = await self.call(GOOD)
        assert stopped[1]["error"] == GUARD.REPEAT_STOP_MESSAGE
        assert GUARD.guard_stopped(self.metadata)
        assert GUARD.guard_state(self.metadata)["failures"] == {}

    def test_internal_refs_are_validated(self):
        schema = {
            "$defs": {"value": {"type": "string"}},
            "type": "object",
            "properties": {"name": {"$ref": "#/$defs/value"}},
        }
        assert "expected type" in GUARD.validation_problem({"name": 1}, schema)

    def test_patcher_rejects_changed_upstream(self):
        with self.assertRaises(ValueError):
            PATCHER.patch("async def changed():\n    pass\n")

    def test_patch_preserves_syntax_and_stop_before_continuation(self):
        source = (
            PATCHER.FUNCTION
            + "    pass\n\nasync def example():\n    while True:\n"
            + PATCHER.CONTINUATION
            + "\n                            'model': 'test',\n                        }\n                    except Exception:\n                        pass\n"
        )
        source += (
            "\ndef file_result(tool_function_name, tool_result):\n"
            + PATCHER.FILE_RESULT
            + "\n        return None\n"
        )
        source += (
            "\nasync def event(tool_function_name, event_emitter, tool_result):\n"
            + PATCHER.EVENT
            + "\n        pass\n"
        )
        patched = PATCHER.patch(source)
        assert "@guarded_execute" in patched
        assert PATCHER.FILE_RESULT_GUARD in patched
        assert PATCHER.EVENT_GUARD in patched
        assert patched.index("if guard_stopped") < patched.index("new_form_data")
        with self.assertRaises(ValueError):
            PATCHER.patch(patched)


class NoProgressRoundTests(unittest.TestCase):
    """Tests for NoProgressRoundTests."""

    def call(self, name, error):
        return [
            {"type": "message", "status": "in_progress"},
            {
                "type": "function_call",
                "call_id": "c1",
                "name": name,
                "arguments": "{}",
                "status": "failed",
            },
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": [{"type": "input_text", "text": error}],
                "status": "failed",
            },
        ]

    def test_three_identical_unresolved_rounds_stop(self):
        metadata = {"message_id": "m", "tools": {}}
        for _ in range(2):
            GUARD.record_no_progress_round(
                metadata, self.call("missing_tool", "Error: Tool not found")
            )
            assert not GUARD.guard_stopped(metadata)
        # output shrinks (new iteration), seen counter must reset with it
        GUARD.record_no_progress_round(metadata, self.call("missing_tool", "Error: Tool not found"))
        assert GUARD.guard_stopped(metadata)
        assert GUARD.guard_stop_message(metadata) == GUARD.NO_PROGRESS_STOP_MESSAGE

    def test_resolving_call_resets_no_progress(self):
        metadata = {"message_id": "m", "tools": {}}
        for _ in range(2):
            GUARD.record_no_progress_round(
                metadata, self.call("missing_tool", "Error: Tool not found")
            )
        executed = [
            {"type": "function_call", "call_id": "c1", "name": "present_tool", "arguments": "{}"},
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": [{"type": "input_text", "text": "ok"}],
                "status": "completed",
            },
        ]
        GUARD.record_no_progress_round(metadata, executed)
        assert not GUARD.guard_stopped(metadata)
        GUARD.record_no_progress_round(metadata, self.call("missing_tool", "Error: Tool not found"))
        assert not GUARD.guard_stopped(metadata)

    def test_alternating_unresolved_rounds_stop(self):
        metadata = {"message_id": "m", "tools": {}}
        rounds = [
            self.call("a", "Error: Tool not found"),
            self.call("b", "Error: unavailable tool"),
        ]
        for index in range(6):
            GUARD.record_no_progress_round(metadata, rounds[index % 2])
        assert GUARD.guard_stopped(metadata)
        assert GUARD.guard_stop_message(metadata) == GUARD.NO_PROGRESS_STOP_MESSAGE

    def test_changing_errors_do_not_stop(self):
        metadata = {"message_id": "m", "tools": {}}
        errors = [
            "Error: Tool not found",
            "Error: bad arguments",
            "Error: schema mismatch",
            "Error: disabled",
        ]
        for error in errors:
            GUARD.record_no_progress_round(metadata, self.call("missing_tool", error))
        assert not GUARD.guard_stopped(metadata)

    def test_round_without_tool_outputs_is_ignored(self):
        metadata = {"message_id": "m", "tools": {}}
        GUARD.record_no_progress_round(metadata, [{"type": "message", "content": []}])
        assert not GUARD.guard_stopped(metadata)
        assert GUARD.guard_state(metadata).get("no_progress") is None

    def test_non_list_output_is_safe(self):
        metadata = {"message_id": "m", "tools": {}}
        GUARD.record_no_progress_round(metadata, None)
        assert not GUARD.guard_stopped(metadata)


if __name__ == "__main__":
    unittest.main()
