import asyncio
import json
import uuid

from open_webui.utils.middleware import execute_tool_call, build_terminal_file_tool_result
from open_webui.utils.homelab_tool_guard import guard_stopped
from open_webui.utils.tools import Config, clean_openai_tool_schema, execute_tool_server, get_tool_servers_data, get_terminal_server_url


def serialize(result):
    if isinstance(result, tuple):
        result = result[0]
    return result if isinstance(result, str) else json.dumps(result)


async def main():
    connections = await Config.get('terminal_server.connections', [])
    connection = next(c for c in connections if c.get('id') == 'socrat-terminal' and c.get('enabled', True))
    config = {'url': get_terminal_server_url(connection), 'key': connection.get('key', ''), 'auth_type': connection.get('auth_type', 'bearer'), 'path': connection.get('path', '/openapi.json'), 'spec_type': 'url', 'config': {'enable': True}, 'info': {'id': connection['id'], 'name': connection.get('name', '')}}
    servers = await get_tool_servers_data([config])
    server = servers[0]
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + connection.get('key', ''), 'X-Session-Id': 'homelab-tool-guard-' + str(uuid.uuid4())}
    specs = {spec['name']: clean_openai_tool_schema(spec) for spec in server['specs']}
    path = '/tmp/homelab-tool-guard-' + uuid.uuid4().hex + '.txt'
    original = 'GUARD_BEFORE_' + uuid.uuid4().hex
    changed = 'GUARD_AFTER_' + uuid.uuid4().hex
    dispatches = 0

    async def raw(name, params):
        return await execute_tool_server(url=server['url'], headers=headers, cookies={}, name=name, params=params, server_data=server)

    async def replace(**params):
        nonlocal dispatches
        dispatches += 1
        return await raw('replace_file_content', params)

    metadata = {'message_id': str(uuid.uuid4()), 'params': {'tool_approval_mode': 'full'}, 'tools': {'replace_file_content': {'type': 'terminal', 'spec': specs['replace_file_content'], 'callable': replace}}}

    async def call(params):
        return await execute_tool_call({'messages': []}, metadata, None, {'id': str(uuid.uuid4()), 'function': {'name': 'replace_file_content', 'arguments': json.dumps(params)}})

    try:
        created = await raw('write_file', {'path': path, 'content': original})
        assert 'error' not in serialize(created).lower(), 'Fixture creation failed'
        for index in range(3):
            result = await call({'path': path, 'replacements': [{'old_text': original, 'new_text': changed}]})
            error = result[1]['error']
            assert 'target' in error and 'replacement' in error
            assert original not in error and changed not in error
            assert guard_stopped(metadata) == (index == 2)
        assert dispatches == 0, 'Invalid calls reached terminal'
        read = await raw('read_file', {'path': path})
        assert original in serialize(read) and changed not in serialize(read), 'Invalid calls changed fixture'
        metadata['message_id'] = str(uuid.uuid4())
        result = await call({'path': path, 'replacements': [{'target': original, 'replacement': changed}]})
        assert dispatches == 1 and not guard_stopped(metadata)
        read = await raw('read_file', {'path': path})
        assert changed in serialize(read) and original not in serialize(read), 'Corrected edit did not change fixture'
        assert build_terminal_file_tool_result('display_file', {'path': path}, {'error': 'validation failed'}, {'tool_id': 'terminal:socrat-terminal'}, {}) is None
    finally:
        cleanup = await raw('run_command', {'command': 'rm -f -- ' + path, 'wait': 10})
        cleanup_body = json.loads(serialize(cleanup))
        for _ in range(2):
            if cleanup_body.get('exit_code') is not None:
                break
            process_id = cleanup_body.get('id') or cleanup_body.get('process_id')
            assert process_id, 'Fixture cleanup returned no process identifier'
            cleanup_body = json.loads(serialize(await raw('get_process_status', {'process_id': process_id, 'wait': 10})))
        assert cleanup_body.get('exit_code') == 0, 'Fixture cleanup did not finish successfully'
    print(json.dumps({'ok': True, 'invalid_calls': 3, 'invalid_dispatches': 0, 'corrected_dispatches': 1, 'file_unchanged_after_invalid': True, 'file_changed_after_correction': True, 'failed_display_has_no_card': True}))


asyncio.run(main())
