import copy
import importlib.util
import json
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / 'charts/llm-switcher/files/context_budget.py'
SPEC = importlib.util.spec_from_file_location('context_budget', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


async def count_tokens(body):
    payload = {key: body[key] for key in ('messages', 'tools', 'tool_choice', 'response_format') if key in body}
    return len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))


async def summarize(messages, max_tokens):
    return 'Preserve the goal, completed work, filenames, and pending verification.'[:max_tokens]


class ContextBudgetTests(unittest.IsolatedAsyncioTestCase):
    def body(self, messages, **extra):
        return {'model': 'qwen3.8-27b', 'messages': messages, 'max_tokens': 16384, **extra}

    def assert_tool_pairs(self, messages):
        outstanding = set()
        for message in messages:
            if message['role'] == 'tool':
                self.assertIn(message['tool_call_id'], outstanding)
                outstanding.remove(message['tool_call_id'])
            else:
                self.assertFalse(outstanding, 'Retained tool calls must have all their replies before the next turn')
                outstanding.update(call['id'] for call in message.get('tool_calls', []))
        self.assertFalse(outstanding)

    async def test_below_threshold_is_unchanged_and_does_not_summarize(self):
        body = self.body([{'role': 'user', 'content': 'x' * 93000}])

        async def forbidden_summary(*args):
            self.fail('Below-threshold requests should not be summarized')

        result, info = await MODULE.compact_chat(body, 114688, count_tokens, forbidden_summary)
        self.assertEqual(result, body)
        self.assertFalse(info['compacted'])

    async def test_compaction_keeps_recent_work_near_target_and_original_immutable(self):
        messages = [{'role': 'system', 'content': 'Follow the user requirements.'}]
        for number in range(12):
            messages.extend([
                {'role': 'user', 'content': f'Task {number}'},
                {'role': 'assistant', 'content': f'Work {number}: ' + 'x' * 10000},
            ])
        messages.append({'role': 'user', 'content': 'Continue verifying final index.html'})
        body = self.body(messages)
        before = copy.deepcopy(body)
        result, info = await MODULE.compact_chat(body, 114688, count_tokens, summarize)
        actual = await count_tokens(result)
        self.assertEqual(body, before)
        self.assertTrue(info['compacted'])
        self.assertLessEqual(actual, 90000)
        self.assertGreater(actual, 70000, 'Compaction must use the requested budget rather than discard most recent work')
        self.assertIn(messages[-1], result['messages'])
        self.assertIn(messages[-2], result['messages'])
        self.assertIn(messages[0], result['messages'])
        self.assertEqual(result['model'], body['model'])
        self.assertEqual(result['max_tokens'], 16384)

    async def test_output_reserve_reduces_budget_for_larger_requested_answer(self):
        body = self.body([{'role': 'user', 'content': 'x' * 96000}], max_completion_tokens=32768)
        body.pop('max_tokens')
        result, info = await MODULE.compact_chat(body, 114688, count_tokens, summarize)
        self.assertLessEqual(await count_tokens(result) + 32768, 114688)
        self.assertEqual(info['output_reserve'], 32768)

    async def test_tool_definitions_and_system_text_consume_budget(self):
        tools = [{'type': 'function', 'function': {'name': 'execute', 'description': 'd' * 10000, 'parameters': {'type': 'object'}}}]
        body = self.body([
            {'role': 'system', 'content': 's' * 10000},
            {'role': 'user', 'content': 'old ' + 'x' * 75000},
            {'role': 'assistant', 'content': 'Completed old work'},
            {'role': 'user', 'content': 'Now verify the result'},
        ], tools=tools)
        result, info = await MODULE.compact_chat(body, 114688, count_tokens, summarize)
        self.assertTrue(info['compacted'])
        self.assertLessEqual(await count_tokens(result), 90000)
        self.assertEqual(result['tools'], tools)
        self.assertEqual(result['messages'][0], body['messages'][0])

    async def test_failed_summary_still_produces_a_bounded_request(self):
        body = self.body([
            {'role': 'user', 'content': 'old ' + 'x' * 130000},
            {'role': 'assistant', 'content': 'Created index.html'},
            {'role': 'user', 'content': 'Inspect index.html and continue'},
        ])

        async def failed_summary(*args):
            raise RuntimeError('summary inference unavailable')

        result, info = await MODULE.compact_chat(body, 114688, count_tokens, failed_summary)
        self.assertLessEqual(await count_tokens(result), 90000)
        self.assertIn(body['messages'][-1], result['messages'])
        self.assertTrue(info['compacted'])

    async def test_giant_tool_response_keeps_protocol_valid(self):
        body = self.body([
            {'role': 'user', 'content': 'Inspect output and continue'},
            {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'read-one', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"one.txt"}'}},
                {'id': 'read-two', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"two.txt"}'}},
            ]},
            {'role': 'tool', 'tool_call_id': 'read-one', 'content': 'x' * 150000},
            {'role': 'tool', 'tool_call_id': 'read-two', 'content': 'second result'},
        ])
        result, info = await MODULE.compact_chat(body, 114688, count_tokens, summarize)
        self.assertLessEqual(await count_tokens(result), 90000)
        self.assert_tool_pairs(result['messages'])
        self.assertTrue(result['messages'])
        self.assertTrue(info['compacted'])

    async def test_image_history_does_not_leave_orphan_tool_results(self):
        body = self.body([
            {'role': 'user', 'content': [{'type': 'text', 'text': 'Inspect this'}, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + 'A' * 130000}}]},
            {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'image-read', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'image-read', 'content': 'Read the image'},
            {'role': 'assistant', 'content': 'Image inspection complete'},
            {'role': 'user', 'content': 'Continue from saved files'},
        ])
        result, _ = await MODULE.compact_chat(body, 114688, count_tokens, summarize)
        self.assertLessEqual(await count_tokens(result), 90000)
        self.assert_tool_pairs(result['messages'])
        self.assertIn(body['messages'][-1], result['messages'])

    async def test_summary_overshooting_its_requested_budget_is_recounted(self):
        body = self.body([
            {'role': 'user', 'content': 'Original task'},
            {'role': 'assistant', 'content': 'x' * 100000},
            {'role': 'user', 'content': 'Continue verification'},
        ])

        async def oversized_summary(*args):
            return 's' * 120000

        result, info = await MODULE.compact_chat(body, 114688, count_tokens, oversized_summary)
        self.assertLessEqual(await count_tokens(result), 90000)
        self.assertIn(body['messages'][-1], result['messages'])
        self.assertTrue(info['compacted'])

    async def test_large_assistant_boundary_retains_partial_work_near_budget(self):
        body = self.body([
            {'role': 'user', 'content': 'Build and verify index.html'},
            {'role': 'assistant', 'content': 'BOUNDARY_WORK: ' + 'x' * 100000},
            {'role': 'user', 'content': 'Continue the last verification'},
        ])
        result, _ = await MODULE.compact_chat(body, 114688, count_tokens, summarize)
        actual = await count_tokens(result)
        self.assertGreaterEqual(actual, 85000)
        self.assertLessEqual(actual, 90000)
        retained = [message for message in result['messages'] if message['role'] == 'assistant']
        self.assertTrue(retained)
        self.assertIn('BOUNDARY_WORK', retained[0]['content'])
        self.assertIn(body['messages'][-1], result['messages'])

    async def test_large_tool_boundary_retains_partial_result_and_complete_protocol(self):
        body = self.body([
            {'role': 'user', 'content': 'Inspect output and verify index.html'},
            {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'boundary-read', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"path":"report.txt"}'}},
            ]},
            {'role': 'tool', 'tool_call_id': 'boundary-read', 'content': 'BOUNDARY_REPORT: ' + 'x' * 100000},
            {'role': 'user', 'content': 'Continue the last verification'},
        ])
        result, _ = await MODULE.compact_chat(body, 114688, count_tokens, summarize)
        actual = await count_tokens(result)
        self.assertGreaterEqual(actual, 85000)
        self.assertLessEqual(actual, 90000)
        self.assert_tool_pairs(result['messages'])
        retained = [message for message in result['messages'] if message['role'] == 'tool']
        self.assertTrue(retained)
        self.assertIn('BOUNDARY_REPORT', retained[0]['content'])
        self.assertIn(body['messages'][-1], result['messages'])

    async def test_summary_expansion_does_not_silently_discard_unsummarized_groups(self):
        markers = [f'UNIQUE_GROUP_{number}:' for number in range(6)]
        body = self.body([
            {'role': 'user', 'content': 'Build and verify index.html'},
            *[{'role': 'assistant', 'content': marker + 'x' * 16000} for marker in markers],
            {'role': 'user', 'content': 'Continue final verification'},
        ])
        summary_inputs = []

        async def expanding_summary(messages, max_tokens):
            summary_inputs.extend(copy.deepcopy(messages))
            return 's' * 16000

        result, _ = await MODULE.compact_chat(body, 114688, count_tokens, expanding_summary)
        retained = json.dumps(result['messages'])
        summarized = json.dumps(summary_inputs)
        for marker in markers:
            self.assertTrue(marker in retained or marker in summarized, f'{marker} was removed without being presented to summarization')
        self.assertLessEqual(await count_tokens(result), 90000)
        self.assertIn(body['messages'][-1], result['messages'])

    async def test_force_compacts_even_below_trigger(self):
        body = self.body([{'role': 'user', 'content': 'x' * 92000}])
        result, info = await MODULE.compact_chat(body, 114688, count_tokens, summarize, force=True)
        self.assertLessEqual(await count_tokens(result), 90000)
        self.assertTrue(info['compacted'])


if __name__ == '__main__':
    unittest.main()
