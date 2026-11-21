"""Tests for the WebUI fetch timeout handling."""

import asyncio
import importlib.util
import json
import pathlib
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fetch_guard", ROOT / "charts/open-webui/files/tool_guard.py"
)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class FetchTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_preserves_page_text(self) -> None:
        with patch.object(GUARD, "FETCH_WORKER", 'import json; print(json.dumps("page text"))'):
            assert await GUARD.bounded_fetch({"url": "https://example.com"}) == "page text"

    async def test_empty_page_is_explicit_error(self) -> None:
        with patch.object(GUARD, "FETCH_WORKER", 'import json; print(json.dumps(""))'):
            assert "error" in await GUARD.bounded_fetch({"url": "https://example.com"})

    async def test_worker_failure_is_explicit_error(self) -> None:
        with patch.object(GUARD, "FETCH_WORKER", "raise SystemExit(2)"):
            assert "error" in await GUARD.bounded_fetch({"url": "https://example.com"})

    async def test_malformed_worker_response_is_explicit_error(self) -> None:
        with patch.object(GUARD, "FETCH_WORKER", 'print("not json")'):
            assert "error" in await GUARD.bounded_fetch({"url": "https://example.com"})

    async def test_worker_start_failure_is_explicit_error(self) -> None:
        with patch.object(GUARD.asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError)):
            assert "error" in await GUARD.bounded_fetch({"url": "https://example.com"})


    async def test_upstream_refusal_does_not_start_fetch(self) -> None:
        async def original(_form_data, _metadata, _event_caller, _call) -> object:
            return {"error": "Tool call was not approved"}

        execute = GUARD.guarded_execute(original)
        with patch.object(GUARD, "bounded_fetch", AsyncMock()) as fetch:
            result = await execute(
                {},
                {"tools": {"fetch_url": {"type": "builtin"}}},
                None,
                {"function": {"name": "fetch_url", "arguments": '{"url":"https://example.com"}'}},
            )
            assert "not approved" in result["error"]
            fetch.assert_not_awaited()

    async def check_termination(self, *, cancel: bool) -> None:
        original = asyncio.create_subprocess_exec
        processes: list[asyncio.subprocess.Process] = []
        started = asyncio.Event()

        async def spawn(*args, **kwargs) -> object:
            process = await original(*args, **kwargs)
            processes.append(process)
            started.set()
            return process

        with (
            patch.object(GUARD, "FETCH_WORKER", "import time; time.sleep(60)"),
            patch.object(GUARD, "FETCH_TIMEOUT_SECONDS", 0.2),
            patch.object(GUARD.asyncio, "create_subprocess_exec", spawn),
        ):
            task = asyncio.create_task(GUARD.bounded_fetch({"url": "https://example.com"}))
            await started.wait()
            if cancel:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            else:
                result = await task
                assert "deadline" in result["error"]
            assert len(processes) == 1
            assert processes[0].returncode is not None
            assert processes[0].returncode != 0

    async def test_deadline_kills_and_reaps_worker(self) -> None:
        await self.check_termination(cancel=False)

    async def test_stop_kills_and_reaps_worker(self) -> None:
        await self.check_termination(cancel=True)


    async def test_only_builtin_fetch_is_intercepted(self) -> None:
        async def original(_form_data, metadata, _event_caller, call) -> object:
            tool = metadata["tools"]["fetch_url"]
            result = await tool["callable"](**json.loads(call["function"]["arguments"]))
            return result

        execute = GUARD.guarded_execute(original)
        call = {
            "function": {
                "name": "fetch_url",
                "arguments": json.dumps({"url": "https://example.com"}),
            }
        }
        upstream = AsyncMock(return_value="upstream")
        tool = {"type": "builtin", "callable": upstream}
        with patch.object(GUARD, "bounded_fetch", AsyncMock(return_value="page")) as fetch:
            assert await execute({}, {"tools": {"fetch_url": tool}}, None, call) == "page"
            assert tool["callable"] is upstream
            upstream.assert_not_awaited()
            fetch.assert_awaited_once()
            for tool in [
                {"type": "external", "callable": upstream},
                {"type": "builtin", "direct": True, "callable": upstream},
            ]:
                assert await execute({}, {"tools": {"fetch_url": tool}}, None, call) == "upstream"
            fetch.assert_awaited_once()

    async def test_invalid_arguments_use_upstream_validation(self) -> None:
        original = AsyncMock(return_value="upstream")
        original.__globals__ = {}
        execute = GUARD.guarded_execute(original)
        for args in ["broken json", "[]", "{}", '{"url": null}']:
            result = await execute(
                {},
                {"tools": {"fetch_url": {"type": "builtin"}}},
                None,
                {"function": {"name": "fetch_url", "arguments": args}},
            )
            assert result == "upstream"


if __name__ == "__main__":
    unittest.main()
