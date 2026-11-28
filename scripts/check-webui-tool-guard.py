"""Check the Open WebUI homelab tool guard behaviour across tool kinds."""

import asyncio
import json
import uuid
from collections.abc import Mapping
from typing import cast

from open_webui.utils.homelab_tool_guard import REPEAT_STOP_MESSAGE, guard_stopped
from open_webui.utils.middleware import (
    build_terminal_file_tool_result,
    execute_tool_call,
)
from open_webui.utils.tools import (
    Config,
    clean_openai_tool_schema,
    execute_tool_server,
    get_terminal_server_url,
    get_tool_servers_data,
)


def serialize(result: object) -> str:
    """Perform the serialize operation."""
    if isinstance(result, tuple):
        result = result[0]
    return result if isinstance(result, str) else json.dumps(result)


async def main() -> None:
    """Run the command-line entry point."""
    connections = await Config.get("terminal_server.connections", [])
    connection = next(
        c for c in connections if c.get("id") == "socrat-terminal" and c.get("enabled", True)
    )
    config = {
        "url": get_terminal_server_url(connection),
        "key": connection.get("key", ""),
        "auth_type": connection.get("auth_type", "bearer"),
        "path": connection.get("path", "/openapi.json"),
        "spec_type": "url",
        "config": {"enable": True},
        "info": {"id": connection["id"], "name": connection.get("name", "")},
    }
    servers = await get_tool_servers_data([config])
    server = servers[0]
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + connection.get("key", ""),
        "X-Session-Id": "homelab-tool-guard-" + str(uuid.uuid4()),
    }
    specs = {spec["name"]: clean_openai_tool_schema(spec) for spec in server["specs"]}
    path = "/tmp/homelab-tool-guard-" + uuid.uuid4().hex + ".txt"
    original = "GUARD_BEFORE_" + uuid.uuid4().hex
    changed = "GUARD_AFTER_" + uuid.uuid4().hex
    dispatches = 0

    async def raw(name: str, params: Mapping[str, object]) -> object:
        return cast(
            "object",
            await execute_tool_server(
                url=server["url"],
                headers=headers,
                cookies={},
                name=name,
                params=params,
                server_data=server,
            ),
        )

    async def replace(**params: object) -> object:
        nonlocal dispatches
        dispatches += 1
        return await raw("replace_file_content", params)

    metadata = {
        "message_id": str(uuid.uuid4()),
        "params": {"tool_approval_mode": "full"},
        "tools": {
            "replace_file_content": {
                "type": "terminal",
                "spec": specs["replace_file_content"],
                "callable": replace,
            }
        },
    }

    async def call(params: Mapping[str, object]) -> tuple[object, dict[str, object]]:
        return cast(
            "tuple[object, dict[str, object]]",
            await execute_tool_call(
                {"messages": []},
                metadata,
                None,
                {
                    "id": str(uuid.uuid4()),
                    "function": {
                        "name": "replace_file_content",
                        "arguments": json.dumps(params),
                    },
                },
            ),
        )

    try:
        created = await raw("write_file", {"path": path, "content": original})
        if "error" in serialize(created).lower():
            msg = "Fixture creation failed"
            raise RuntimeError(msg)
        for should_stop in (False, False, True):
            result = await call(
                {
                    "path": path,
                    "replacements": [{"old_text": original, "new_text": changed}],
                }
            )
            error = cast("str", result[1]["error"])
            if "target" not in error:
                msg = "Guard error must explain the reviewed field name"
                raise RuntimeError(msg)
            if "replacement" not in error:
                msg = "Guard error must explain the corrected field name"
                raise RuntimeError(msg)
            if original in error:
                msg = "Guard error must not leak the fixture content"
                raise RuntimeError(msg)
            if changed in error:
                msg = "Guard error must not leak the fixture replacement"
                raise RuntimeError(msg)
            if guard_stopped(metadata) != should_stop:
                msg = "Guard stop flag must match the reviewed sequence"
                raise RuntimeError(msg)
        if dispatches != 0:
            msg = "Invalid calls reached terminal"
            raise RuntimeError(msg)
        read = await raw("read_file", {"path": path})
        serialized_read = serialize(read)
        if original not in serialized_read:
            msg = "Invalid calls changed fixture"
            raise RuntimeError(msg)
        if changed in serialized_read:
            msg = "Invalid calls changed fixture"
            raise RuntimeError(msg)
        metadata["message_id"] = str(uuid.uuid4())
        result = await call(
            {
                "path": path,
                "replacements": [{"target": original, "replacement": changed}],
            }
        )
        if dispatches != 1:
            msg = "Corrected call must dispatch exactly once"
            raise RuntimeError(msg)
        if guard_stopped(metadata):
            msg = "Corrected call must not trip the guard"
            raise RuntimeError(msg)
        read = await raw("read_file", {"path": path})
        serialized_read = serialize(read)
        if changed not in serialized_read:
            msg = "Corrected edit did not change fixture"
            raise RuntimeError(msg)
        if original in serialized_read:
            msg = "Corrected edit did not change fixture"
            raise RuntimeError(msg)
        if (
            build_terminal_file_tool_result(
                "display_file",
                {"path": path},
                {"error": "validation failed"},
                {"tool_id": "terminal:socrat-terminal"},
                {},
            )
            is not None
        ):
            msg = "Failed display tool must produce no card"
            raise RuntimeError(msg)
        # Repeated identical valid calls warn first and then stop the loop.
        metadata["message_id"] = str(uuid.uuid4())
        cast("dict[str, object]", metadata["tools"])["read_file"] = {
            "type": "terminal",
            "spec": specs["read_file"],
        }

        async def read(params: Mapping[str, object]) -> tuple[object, dict[str, object] | str]:
            async def dispatch(**_kwargs: object) -> object:
                return await raw("read_file", params)

            cast(
                "dict[str, object]",
                cast("dict[str, object]", metadata["tools"])["read_file"],
            )["callable"] = dispatch
            return cast(
                "tuple[object, dict[str, object] | str]",
                await execute_tool_call(
                    {"messages": []},
                    metadata,
                    None,
                    {
                        "id": str(uuid.uuid4()),
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps(params),
                        },
                    },
                ),
            )

        identical = {"path": path}
        await read(identical)
        await read(identical)
        warned = await read(identical)
        error = serialize(warned[1])
        if "not run again" not in error:
            msg = "Third identical valid call did not warn"
            raise RuntimeError(msg)
        if guard_stopped(metadata):
            msg = "Warning must not stop the loop yet"
            raise RuntimeError(msg)
        stopped = await read(identical)
        stopped_payload = stopped[1]
        error = (
            cast("str", stopped_payload.get("error"))
            if isinstance(stopped_payload, dict)
            else serialize(stopped_payload)
        )
        if not guard_stopped(metadata):
            msg = "Fourth identical valid call did not stop the loop"
            raise RuntimeError(msg)
        if error != REPEAT_STOP_MESSAGE:
            msg = "Repeat stop must use the reviewed stop message"
            raise RuntimeError(msg)
        # A genuinely different command clears the warning in a fresh response.
        metadata["message_id"] = str(uuid.uuid4())
        await read({"path": path + ".missing"})
        if guard_stopped(metadata):
            msg = "Fresh response inherited repeat stop"
            raise RuntimeError(msg)
    finally:
        cleanup = await raw("run_command", {"command": "rm -f -- " + path, "wait": 10})
        cleanup_body = json.loads(serialize(cleanup))
        for _ in range(2):
            if cleanup_body.get("exit_code") is not None:
                break
            process_id = cleanup_body.get("id") or cleanup_body.get("process_id")
            if not process_id:
                msg = "Fixture cleanup returned no process identifier"
                raise RuntimeError(msg)
            cleanup_body = json.loads(
                serialize(await raw("get_process_status", {"process_id": process_id, "wait": 10}))
            )
        if cleanup_body.get("exit_code") != 0:
            msg = "Fixture cleanup did not finish successfully"
            raise RuntimeError(msg)
    print(
        json.dumps(
            {
                "ok": True,
                "invalid_calls": 3,
                "invalid_dispatches": 0,
                "corrected_dispatches": 1,
                "file_unchanged_after_invalid": True,
                "file_changed_after_correction": True,
                "failed_display_has_no_card": True,
                "repeat_warn_stopped": True,
                "repeat_reset_per_response": True,
            }
        )
    )


asyncio.run(main())
