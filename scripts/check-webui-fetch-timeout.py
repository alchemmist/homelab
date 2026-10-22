import asyncio
import json
import time
from unittest.mock import patch

from open_webui.models.config import Config
from open_webui.utils import homelab_tool_guard as guard
from open_webui.utils.middleware import execute_tool_call


async def main():
    assert await Config.get('web.loader.timeout') == '15'
    metadata = {'tools': {'fetch_url': {'type': 'builtin', 'spec': {'name': 'fetch_url', 'parameters': {'properties': {'url': {'type': 'string'}}}}}}}

    async def call(url):
        return await execute_tool_call({}, metadata, None, {'function': {'name': 'fetch_url', 'arguments': json.dumps({'url': url})}})

    with patch.object(guard, 'FETCH_WORKER', 'import json; print(json.dumps("healthy page"))'):
        response = await call('https://example.com')
        assert response[1] == 'healthy page', response

    processes = []
    spawn = asyncio.create_subprocess_exec

    async def record_process(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        processes.append(process)
        return process

    with patch.object(guard, 'FETCH_WORKER', 'import time; time.sleep(60)'), patch.object(guard, 'FETCH_TIMEOUT_SECONDS', 0.2), patch.object(guard.asyncio, 'create_subprocess_exec', record_process):
        response = await call('https://example.com')
        assert 'deadline' in response[1]['error'], response
        assert processes[0].returncode is not None

    start = time.monotonic()
    response = await call('https://thanos.io/v0.8/components/compact/')
    elapsed = time.monotonic() - start
    assert elapsed < guard.FETCH_TIMEOUT_SECONDS + 5, elapsed
    result = response[1]
    assert isinstance(result, (str, dict)) and result, result
    print(json.dumps({'ok': True, 'deadline_worker_reaped': True, 'thanos_seconds': round(elapsed, 2), 'thanos_result': 'error' if isinstance(result, dict) else 'page'}))


asyncio.run(main())
