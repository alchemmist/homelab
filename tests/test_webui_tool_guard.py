import importlib.util
import json
import pathlib
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'charts/open-webui/files' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = load('tool_guard')
PATCHER = load('patch_tool_guard')
SCHEMA = {'type': 'object', 'properties': {'path': {'type': 'string'}, 'replacements': {'type': 'array', 'items': {'type': 'object', 'required': ['target', 'replacement'], 'properties': {'target': {'type': 'string'}, 'replacement': {'type': 'string'}}}}}, 'required': ['path', 'replacements']}
BAD = {'path': '/tmp/example', 'replacements': [{'old_text': 'PRIVATE CODE', 'new_text': 'PRIVATE CODE 2'}]}
GOOD = {'path': '/tmp/example', 'replacements': [{'target': 'old', 'replacement': 'new'}]}


class ToolGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.metadata = {'message_id': 'one', 'tools': {'replace_file_content': {'type': 'terminal', 'spec': {'parameters': SCHEMA}}}}
        self.calls = 0
        self.result = {'success': True}

        async def execute(form_data, metadata, event_caller, call):
            self.calls += 1
            return json.loads(call['function']['arguments']), self.result, metadata['tools']['replace_file_content'], 'terminal', False

        self.execute = GUARD.guarded_execute(execute)

    async def call(self, params=BAD, raw=None):
        return await self.execute({}, self.metadata, None, {'function': {'name': 'replace_file_content', 'arguments': raw if raw is not None else json.dumps(params)}})

    async def test_nested_validation_is_concise_and_never_executes(self):
        result = await self.call()
        error = result[1]['error']
        self.assertIn('target, replacement', error)
        self.assertIn('not executed', error)
        self.assertNotIn('PRIVATE', error)
        self.assertEqual(self.calls, 0)
        self.assertLess(len(error), 600)

    async def test_third_identical_invalid_call_stops_despite_formatting(self):
        await self.call()
        await self.call(raw=json.dumps(BAD, sort_keys=True, indent=4))
        self.assertFalse(GUARD.guard_stopped(self.metadata))
        await self.call()
        self.assertTrue(GUARD.guard_stopped(self.metadata))
        result = await self.call(GOOD)
        self.assertEqual(result[1]['error'], GUARD.STOP_MESSAGE)
        self.assertEqual(self.calls, 0)

    async def test_valid_calls_are_unchanged(self):
        result = await self.call(GOOD)
        self.assertEqual(result[1], self.result)
        self.assertEqual(self.calls, 1)

    async def test_unrelated_success_does_not_hide_same_invalid_call(self):
        await self.call()
        await self.call(GOOD)
        await self.call()
        await self.call(GOOD)
        await self.call()
        self.assertTrue(GUARD.guard_stopped(self.metadata))
        self.assertEqual(self.calls, 2)

    async def test_corrected_arguments_allow_recovery(self):
        await self.call()
        await self.call(GOOD)
        self.assertEqual(self.calls, 1)
        self.assertFalse(GUARD.guard_stopped(self.metadata))

    async def test_identical_valid_calls_warn_then_stop(self):
        await self.call(GOOD)
        await self.call(GOOD)
        warned = await self.call(GOOD)
        self.assertEqual(self.calls, 2)
        self.assertIn('not run again', warned[1]['error'])
        self.assertFalse(GUARD.guard_stopped(self.metadata))
        stopped = await self.call(GOOD)
        self.assertTrue(GUARD.guard_stopped(self.metadata))
        self.assertEqual(self.calls, 2)
        self.assertEqual(stopped[1]['error'], GUARD.REPEAT_STOP_MESSAGE)
        self.assertEqual(GUARD.guard_stop_message(self.metadata), GUARD.REPEAT_STOP_MESSAGE)

    async def test_alternating_valid_calls_escalate_to_stop(self):
        other = {'path': '/tmp/other', 'replacements': [{'target': 'x', 'replacement': 'y'}]}
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
        self.assertTrue(GUARD.guard_stopped(self.metadata))
        self.assertLess(self.calls, executed)
        self.assertGreaterEqual(self.calls, 4)

    async def test_varied_calls_reset_repeat_warning(self):
        other = {'path': '/tmp/other', 'replacements': []}
        await self.call(GOOD)
        await self.call(GOOD)
        warned = await self.call(GOOD)
        self.assertIn('not run again', warned[1]['error'])
        self.assertFalse(GUARD.guard_stopped(self.metadata))
        recovered = await self.call(other)
        self.assertEqual(recovered[1], self.result)
        self.assertEqual(self.calls, 3)
        await self.call(GOOD)
        self.assertEqual(self.calls, 4)
        await self.call(GOOD)
        self.assertEqual(self.calls, 5)
        warned_again = await self.call(GOOD)
        self.assertIn('not run again', warned_again[1]['error'])
        self.assertEqual(self.calls, 5)
        self.assertFalse(GUARD.guard_stopped(self.metadata))
        stopped = await self.call(GOOD)
        self.assertTrue(GUARD.guard_stopped(self.metadata))
        self.assertEqual(stopped[1]['error'], GUARD.REPEAT_STOP_MESSAGE)

    async def test_alias_resolved_before_validation(self):
        def resolve(call, tools):
            call['function']['name'] = 'replace_file_content'
            return None

        with patch.dict(self.execute.__wrapped__.__globals__, {'resolve_tool_call': resolve}):
            result = await self.execute({}, self.metadata, None, {'function': {'name': 'terminal_replace_alias', 'arguments': json.dumps(BAD)}})
        self.assertIn('target', result[1]['error'])
        self.assertEqual(self.calls, 0)

    async def test_non_terminal_is_not_intercepted(self):
        self.metadata['tools']['replace_file_content']['type'] = 'external'
        await self.call()
        self.assertEqual(self.calls, 1)

    async def test_next_message_resets_guard(self):
        for _ in range(3):
            await self.call()
        self.metadata['message_id'] = 'two'
        await self.call(GOOD)
        self.assertEqual(self.calls, 1)
        self.assertFalse(GUARD.guard_stopped(self.metadata))

    async def test_chats_are_isolated(self):
        for _ in range(3):
            await self.call()
        other = {'message_id': 'one', 'tools': self.metadata['tools']}
        self.assertFalse(GUARD.guard_stopped(other))

    async def test_malformed_json_and_nonobject_safe(self):
        result = await self.call(raw='{"unfinished":')
        self.assertIn('complete JSON', result[1]['error'])
        result = await self.call(raw='[]')
        self.assertEqual(result[0], {})
        self.assertEqual(self.calls, 0)

    async def test_backend_422_compacted_and_bounded(self):
        self.result = ({'error': 'HTTP error 422: {"input":"PRIVATE CODE"}'}, None)
        for _ in range(3):
            result = await self.call(GOOD)
        self.assertTrue(GUARD.guard_stopped(self.metadata))
        self.assertNotIn('PRIVATE', result[1]['error'])
        self.assertEqual(self.calls, 3)

    async def test_backend_other_errors_do_not_count(self):
        self.result = {'error': 'HTTP error 503: unavailable'}
        first = await self.call(GOOD)
        second = await self.call(GOOD)
        self.assertEqual(first[1], self.result)
        self.assertEqual(second[1], self.result)
        self.assertFalse(GUARD.guard_stopped(self.metadata))
        self.assertEqual(GUARD.guard_state(self.metadata)['failures'], {})
        warned = await self.call(GOOD)
        self.assertIn('not run again', warned[1]['error'])
        stopped = await self.call(GOOD)
        self.assertEqual(stopped[1]['error'], GUARD.REPEAT_STOP_MESSAGE)
        self.assertTrue(GUARD.guard_stopped(self.metadata))
        self.assertEqual(GUARD.guard_state(self.metadata)['failures'], {})

    def test_internal_refs_are_validated(self):
        schema = {'$defs': {'value': {'type': 'string'}}, 'type': 'object', 'properties': {'name': {'$ref': '#/$defs/value'}}}
        self.assertIn('expected type', GUARD.validation_problem({'name': 1}, schema))

    def test_patcher_rejects_changed_upstream(self):
        with self.assertRaises(ValueError):
            PATCHER.patch('async def changed():\n    pass\n')

    def test_patch_preserves_syntax_and_stop_before_continuation(self):
        source = PATCHER.FUNCTION + '    pass\n\nasync def example():\n    while True:\n' + PATCHER.CONTINUATION + "\n                            'model': 'test',\n                        }\n                    except Exception:\n                        pass\n"
        source += "\ndef file_result(tool_function_name, tool_result):\n" + PATCHER.FILE_RESULT + "\n        return None\n"
        source += "\nasync def event(tool_function_name, event_emitter, tool_result):\n" + PATCHER.EVENT + "\n        pass\n"
        patched = PATCHER.patch(source)
        self.assertIn('@guarded_execute', patched)
        self.assertIn(PATCHER.FILE_RESULT_GUARD, patched)
        self.assertIn(PATCHER.EVENT_GUARD, patched)
        self.assertLess(patched.index('if guard_stopped'), patched.index('new_form_data'))
        with self.assertRaises(ValueError):
            PATCHER.patch(patched)


if __name__ == '__main__':
    unittest.main()
