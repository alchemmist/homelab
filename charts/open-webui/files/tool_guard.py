import ast
import asyncio
import functools
import hashlib
import json
import sys
from itertools import islice

from jsonschema import Draft202012Validator

STATE_KEY = 'homelab_terminal_validation_guard'
STOP_MESSAGE = 'Stopped repeated invalid terminal calls. Your conversation and files are preserved. Correct the tool arguments before continuing.'
MAX_IDENTICAL_FAILURES = 3
REPEAT_PERIODS = (1, 2, 3)
REPEAT_CYCLES = 3
REPEAT_HISTORY = 64
REPEAT_WARN_MESSAGE = 'This exact terminal call sequence was already executed {cycles} times in a row with identical arguments, so this call was not run again. Repeating it further will stop the response. Verify the current state with a different command, or summarize your findings and finish.'
REPEAT_STOP_MESSAGE = 'Stopped repeated identical terminal calls. Your conversation and files are preserved. The identical call is repeated without progress; describe the current state and finish, or continue with a genuinely different action.'
NO_PROGRESS_HISTORY = 9
NO_PROGRESS_STOP_MESSAGE = 'Stopped a degenerate tool-call loop. The same tool calls failed to run in the same way three cycles in a row, and no tool executed. Your conversation and files are preserved. Check that the failing tool is enabled in this chat and matches the expected name and argument schema, then continue with a corrected or different call, or answer directly.'
FETCH_TIMEOUT_SECONDS = 45
FETCH_WORKER = '''
import asyncio
import contextlib
import json
import sys

with contextlib.redirect_stdout(sys.stderr):
    from open_webui.tools.builtin import fetch_url
    arguments = json.load(sys.stdin)
    result = asyncio.run(fetch_url(arguments['url'], __request__=object()))
print(json.dumps(result))
'''


async def bounded_fetch(params):
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-c', FETCH_WORKER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return {'error': 'fetch_url could not start its worker. Try again later.'}
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(json.dumps(params).encode()), FETCH_TIMEOUT_SECONDS,
        )
        if process.returncode:
            return {'error': 'fetch_url failed while loading the page. Try another source.'}
        result = json.loads(stdout)
        if not isinstance(result, str) or not result.strip():
            return {'error': 'fetch_url could not load the page (network error, timeout, or empty response). Try another source.'}
        return result
    except TimeoutError:
        return {'error': f'fetch_url exceeded its {FETCH_TIMEOUT_SECONDS}-second deadline. Try another source; do not repeatedly retry this URL.'}
    except (ValueError, OSError):
        return {'error': 'fetch_url worker returned an invalid response. Try another source.'}
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()


def validation_problem(params, schema):
    try:
        errors = list(islice(Draft202012Validator(schema).iter_errors(params), 4))
    except Exception:
        return None
    if not errors:
        return None
    problems = []
    for error in errors[:4]:
        path = '.'.join(str(part) for part in error.absolute_path) or 'arguments'
        if error.validator == 'required':
            missing = [key for key in error.validator_value if key not in error.instance]
            detail = 'missing required fields: ' + ', '.join(missing)
        elif error.validator == 'type':
            detail = 'expected type ' + str(error.validator_value)
        else:
            detail = 'does not match schema rule ' + str(error.validator)
        problems.append(f'{path}: {detail}')
    return '; '.join(problems)


def repeated_period(fingerprints, periods=REPEAT_PERIODS, cycles=REPEAT_CYCLES):
    for period in periods:
        need = period * cycles
        if len(fingerprints) >= need and fingerprints[-need:] == fingerprints[-period:] * cycles:
            return period
    return None


def record_failure(metadata, name, arguments, problem):
    state = guard_state(metadata)
    fingerprint = hashlib.sha256((name + '\n' + arguments).encode()).hexdigest()
    failures = state['failures']
    if len(failures) >= 128 and fingerprint not in failures:
        failures.pop(next(iter(failures)))
    count = failures.get(fingerprint, 0) + 1
    failures[fingerprint] = count
    state['stopped'] = state['stopped'] or count >= MAX_IDENTICAL_FAILURES
    state['stop_message'] = state.get('stop_message') or (STOP_MESSAGE if state['stopped'] else None)
    suffix = STOP_MESSAGE if state['stopped'] else 'Correct the arguments using the tool schema before retrying. Do not inspect screenshots as evidence of an unapplied edit.'
    return {'error': f'Tool validation failed; the operation was not executed. {problem}. Identical invalid call {count}/{MAX_IDENTICAL_FAILURES}. {suffix}'}


def guard_state(metadata):
    generation = metadata.get('message_id') or metadata.get('assistant_message_id')
    state = metadata.get(STATE_KEY)
    if not isinstance(state, dict) or state.get('generation') != generation:
        state = {'generation': generation, 'failures': {}, 'recent': [], 'warned': None, 'stopped': False, 'stop_message': None}
        metadata[STATE_KEY] = state
    return state


def guard_stopped(metadata):
    return guard_state(metadata)['stopped']


def guard_stop_message(metadata):
    return guard_state(metadata).get('stop_message') or STOP_MESSAGE


def record_no_progress_round(metadata, output):
    """Track rounds whose every tool call failed before execution.

    Calls that resolve_tool_call rejects never reach guarded_execute, so the
    invalid-call and repeat-call guards cannot see them. A round whose every
    function_call_output carries status 'failed' executed no tool at all.
    Repeating the same all-failed round 1-3 times over in a fixed pattern
    means the model cannot make progress; the response is stopped with a
    message explaining what to fix. Any round with a resolving call resets
    the pattern, so honest work is unaffected.
    """
    state = guard_state(metadata)
    if not isinstance(output, list):
        return
    seen = state.get('no_progress_seen') or 0
    if id(output) != state.get('no_progress_output_id'):
        # The loop rebinds output to a fresh list for every generated response.
        seen = 0
        state['no_progress_output_id'] = id(output)
    if seen > len(output):
        seen = 0
    new_items = output[seen:]
    state['no_progress_seen'] = len(output)
    outputs = [item for item in new_items if isinstance(item, dict) and item.get('type') == 'function_call_output']
    if not outputs:
        return
    history = state.setdefault('no_progress', [])
    if not all(item.get('status') == 'failed' for item in outputs):
        history.clear()
        return
    calls = {
        item.get('call_id'): item
        for item in new_items
        if isinstance(item, dict) and item.get('type') == 'function_call' and item.get('call_id')
    }
    signature = []
    for item in sorted(outputs, key=lambda item: str(item.get('call_id'))):
        call = calls.get(item.get('call_id'), {})
        signature.append((str(call.get('name', '')), repr(item.get('output'))))
    history.append(hashlib.sha256(repr(signature).encode()).hexdigest())
    del history[:-NO_PROGRESS_HISTORY]
    if repeated_period(history):
        state['stopped'] = True
        state['stop_message'] = NO_PROGRESS_STOP_MESSAGE


def backend_validation_problem(result):
    value = result
    if isinstance(value, tuple) and value:
        value = value[0]
    if not isinstance(value, dict):
        return None
    error = value.get('error')
    if not isinstance(error, str) or not error.startswith('HTTP error 422:'):
        return None
    return 'terminal rejected the arguments with HTTP 422; recheck required fields and types in its schema'


def guarded_execute(function):
    @functools.wraps(function)
    async def wrapped(form_data, metadata, event_caller, tool_call):
        resolver = function.__globals__.get('resolve_tool_call')
        if resolver is not None:
            error = resolver(tool_call, metadata.get('tools', {}))
            if error:
                return await function(form_data, metadata, event_caller, tool_call)
        call = tool_call.get('function', {})
        name = call.get('name', '')
        tool = metadata.get('tools', {}).get(name, {})
        if name == 'fetch_url' and tool.get('type') == 'builtin' and not tool.get('direct'):
            async def fetch(url):
                return await bounded_fetch({'url': url})

            tools = {**metadata['tools'], name: {**tool, 'callable': fetch}}
            return await function(form_data, {**metadata, 'tools': tools}, event_caller, tool_call)
        if tool.get('type') != 'terminal':
            return await function(form_data, metadata, event_caller, tool_call)
        direct = tool.get('direct', False)
        if guard_stopped(metadata):
            return {}, {'error': guard_stop_message(metadata)}, tool, 'terminal', direct
        arguments = call.get('arguments', '{}')
        try:
            try:
                params = json.loads(arguments)
            except (ValueError, TypeError):
                params = ast.literal_eval(arguments)
            canonical = json.dumps(params, sort_keys=True, separators=(',', ':'))
        except (ValueError, TypeError, SyntaxError):
            params = {}
            canonical = str(arguments)
            problem = 'arguments must be a complete JSON object'
        else:
            problem = 'arguments must be a JSON object' if not isinstance(params, dict) else validation_problem(params, tool.get('spec', {}).get('parameters', {}))
        if problem:
            result = record_failure(metadata, name, canonical, problem)
            return params if isinstance(params, dict) else {}, result, tool, 'terminal', direct
        fingerprint = hashlib.sha256((name + '\n' + canonical).encode()).hexdigest()
        state = guard_state(metadata)
        recent = state.setdefault('recent', [])
        projected = recent[-(REPEAT_HISTORY - 1):] + [fingerprint]
        period = repeated_period(projected)
        if period:
            block = hashlib.sha256('\n'.join(projected[-period:]).encode()).hexdigest()
            if state.get('warned') == block:
                state['stopped'] = True
                state['stop_message'] = REPEAT_STOP_MESSAGE
                return params, {'error': REPEAT_STOP_MESSAGE}, tool, 'terminal', direct
            state['warned'] = block
            return params, {'error': REPEAT_WARN_MESSAGE.format(cycles=REPEAT_CYCLES)}, tool, 'terminal', direct
        response = await function(form_data, metadata, event_caller, tool_call)
        problem = backend_validation_problem(response[1])
        if problem:
            return response[0], record_failure(metadata, name, canonical, problem), *response[2:]
        state['warned'] = None if fingerprint not in recent else state.get('warned')
        recent.append(fingerprint)
        del recent[:-REPEAT_HISTORY]
        value = response[1]
        if isinstance(value, tuple) and value:
            value = value[0]
        if value is not None and not (isinstance(value, dict) and value.get('error')):
            guard_state(metadata)['failures'].pop(fingerprint, None)
        return response
    return wrapped
