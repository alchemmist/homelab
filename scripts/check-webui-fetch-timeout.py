"""Check the web fetch timeout setting and fetch tool call behaviour."""

import asyncio
import json
import time
from typing import IO, cast
from unittest.mock import patch

from open_webui.models.config import Config
from open_webui.utils import homelab_tool_guard as guard
from open_webui.utils.middleware import execute_tool_call


async def main() -> None:
    """Run the command-line entry point."""
    if await Config.get("web.loader.timeout") != "15":
        msg = "web.loader.timeout drifted from the reviewed 15 seconds"
        raise RuntimeError(msg)
    metadata = {
        "tools": {
            "fetch_url": {
                "type": "builtin",
                "spec": {
                    "name": "fetch_url",
                    "parameters": {"properties": {"url": {"type": "string"}}},
                },
            }
        }
    }

    async def call(url: str) -> tuple[object, object]:
        return cast(
            "tuple[object, object]",
            await execute_tool_call(
                {},
                metadata,
                None,
                {
                    "function": {
                        "name": "fetch_url",
                        "arguments": json.dumps({"url": url}),
                    }
                },
            ),
        )

    with patch.object(guard, "FETCH_WORKER", 'import json; print(json.dumps("healthy page"))'):
        response = await call("https://example.com")
        if response[1] != "healthy page":
            msg = "Healthy-page fetch returned unreviewed content: " + repr(response)
            raise RuntimeError(msg)

    processes = []
    spawn = asyncio.create_subprocess_exec

    async def record_process(
        program: str,
        *args: str,
        stdin: int | IO[bytes] | None = asyncio.subprocess.PIPE,
        stdout: int | IO[bytes] | None = asyncio.subprocess.PIPE,
        stderr: int | IO[bytes] | None = asyncio.subprocess.DEVNULL,
    ) -> asyncio.subprocess.Process:
        process = await spawn(program, *args, stdin=stdin, stdout=stdout, stderr=stderr)
        processes.append(process)
        return process

    with (
        patch.object(guard, "FETCH_WORKER", "import time; time.sleep(60)"),
        patch.object(guard, "FETCH_TIMEOUT_SECONDS", 0.2),
        patch.object(guard.asyncio, "create_subprocess_exec", record_process),
    ):
        response = await call("https://example.com")
        payload = cast("dict[str, object]", response[1])
        error = cast("str", payload["error"])
        if "deadline" not in error:
            msg = "Fetch deadline not reported: " + repr(response)
            raise RuntimeError(msg)
        if processes[0].returncode is None:
            msg = "Timed-out fetch worker was not reaped"
            raise RuntimeError(msg)

    start = time.monotonic()
    response = await call("https://thanos.io/v0.8/components/compact/")
    elapsed = time.monotonic() - start
    if elapsed >= guard.FETCH_TIMEOUT_SECONDS + 5:
        msg = "Thanos fetch exceeded the timeout budget: " + str(elapsed)
        raise RuntimeError(msg)
    result = response[1]
    if not isinstance(result, (str, dict)) or not result:
        msg = "Thanos fetch returned an empty or unexpected payload: " + repr(result)
        raise RuntimeError(msg)
    print(
        json.dumps(
            {
                "ok": True,
                "deadline_worker_reaped": True,
                "thanos_seconds": round(elapsed, 2),
                "thanos_result": "error" if isinstance(result, dict) else "page",
            }
        )
    )


asyncio.run(main())
