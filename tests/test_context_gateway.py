import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / 'charts/llm-switcher/files/server.py'
PROFILES_TEXT = (SOURCE_PATH.parent / 'profiles.json').read_text()
READ_TEXT = Path.read_text
sys.path.insert(0, str(SOURCE_PATH.parent))


def read_config(path, *args, **kwargs):
    if str(path) == '/config/profiles.json':
        return PROFILES_TEXT
    return READ_TEXT(path, *args, **kwargs)


with patch.dict(os.environ, {'BACKEND_API_KEY': 'test-key'}), patch.object(Path, 'read_text', read_config):
    SPEC = importlib.util.spec_from_file_location('context_gateway_test_subject', SOURCE_PATH)
    gateway_module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(gateway_module)


class ContextGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.tokenize_status = 200
        self.summary_status = 200
        self.context_rejections = 0
        self.final_bodies = []
        backend = web.Application(client_max_size=2 * 1024 * 1024)
        backend.router.add_post('/tokenize', self.tokenize)
        backend.router.add_post('/v1/chat/completions', self.completions)
        self.backend = TestServer(backend)
        await self.backend.start_server()
        self.backend_patch = patch.object(gateway_module, 'BACKEND', str(self.backend.make_url('')).rstrip('/'))
        self.backend_patch.start()
        with patch.object(gateway_module.ssl, 'create_default_context', return_value=None):
            self.gateway = gateway_module.Gateway()
        self.gateway.scheduler = gateway_module.ModelScheduler(grace=0)
        self.gateway.session = ClientSession()

        async def ensure_model(model):
            self.assertEqual(model, 'qwen3.8-27b')

        self.gateway.ensure_model = ensure_model
        app = web.Application(client_max_size=2 * 1024 * 1024)
        app.router.add_route('*', '/{path:.*}', self.gateway.handle)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.gateway.session.close()
        await self.backend.close()
        self.backend_patch.stop()

    def count(self, body):
        selected = {key: body[key] for key in ('messages', 'tools', 'chat_template_kwargs') if key in body}
        return len(json.dumps(selected, ensure_ascii=False, separators=(',', ':')))

    async def tokenize(self, request):
        body = await request.json()
        self.requests.append((request.path, body, dict(request.headers)))
        if self.tokenize_status != 200:
            return web.json_response({'error': 'tokenization failed'}, status=self.tokenize_status)
        return web.json_response({'count': self.count(body)})

    async def completions(self, request):
        raw = await request.read()
        self.assertEqual(int(request.headers['Content-Length']), len(raw))
        body = json.loads(raw)
        self.requests.append((request.path, body, dict(request.headers)))
        if body.get('temperature') == 0.1:
            if self.summary_status != 200:
                return web.json_response({'error': 'summarization failed'}, status=self.summary_status)
            return web.json_response({'choices': [{'message': {'content': 'Continue the user task. index.html exists; browser validation remains.'}}]})
        self.final_bodies.append(body)
        if self.context_rejections:
            self.context_rejections -= 1
            return web.json_response({'error': {'message': 'Maximum context length exceeded; input_tokens too large'}}, status=400)
        return web.Response(text='data: {"choices":[]}\n\ndata: [DONE]\n\n', content_type='text/event-stream')

    def large_body(self):
        messages = [{'role': 'system', 'content': 'Complete the requested project and verify it.'}]
        for number in range(12):
            messages.extend([
                {'role': 'user', 'content': f'Work item {number}'},
                {'role': 'assistant', 'content': 'x' * 10000},
            ])
        messages.append({'role': 'user', 'content': 'Verify the final image and continue'})
        return {'model': 'qwen3.8-27b', 'messages': messages}

    async def test_tokenization_receives_images_tools_and_template_options(self):
        body = {
            'model': 'qwen3.8-27b',
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': 'Inspect image'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}},
            ]}],
            'tools': [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object'}}}],
            'chat_template_kwargs': {'custom_setting': True},
            'reasoning_effort': 'none',
            'documents': [{'title': 'Reference', 'text': 'Document contents'}],
            'mm_processor_kwargs': {'max_pixels': 1048576},
            'max_tokens': 16384,
        }
        before = copy.deepcopy(body)
        count = await self.gateway.count_context(body)
        path, payload, headers = self.requests[-1]
        self.assertEqual(path, '/tokenize')
        self.assertEqual(payload['messages'], body['messages'])
        self.assertEqual(payload['tools'], body['tools'])
        self.assertEqual(payload['mm_processor_kwargs'], body['mm_processor_kwargs'])
        self.assertEqual(payload['chat_template_kwargs'], {
            'custom_setting': True,
            'reasoning_effort': 'none',
            'enable_thinking': False,
            'documents': body['documents'],
        })
        self.assertNotIn('max_tokens', payload)
        self.assertEqual(headers['Authorization'], 'Bearer test-key')
        self.assertEqual(count, self.count(payload))
        self.assertEqual(body, before)

    async def test_default_output_reserve_is_explicit_in_forwarded_body(self):
        raw = json.dumps({'model': 'qwen3.8-27b', 'messages': [{'role': 'user', 'content': 'Hello'}]}).encode()
        result, info = await self.gateway.prepare_context(raw, 'qwen3.8-27b')
        self.assertEqual(json.loads(result)['max_tokens'], 16384)
        self.assertEqual(info['output_reserve'], 16384)
        self.assertFalse(info['compacted'])
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(path == '/tokenize' for path, _, _ in self.requests))

    async def test_summary_goes_direct_to_backend_without_reentering_scheduler(self):
        messages = [{'role': 'system', 'content': 'Summarize history'}, {'role': 'user', 'content': 'Created index.html'}]
        async with self.gateway.scheduler.slot('qwen3.8-27b'):
            summary = await self.gateway.summarize_context('qwen3.8-27b', messages, 2048)
        self.assertIn('index.html', summary)
        self.assertEqual([path for path, _, _ in self.requests], ['/tokenize', '/v1/chat/completions'])
        payload = self.requests[-1][1]
        self.assertEqual(payload['max_tokens'], 2048)
        self.assertEqual(payload['chat_template_kwargs'], {'enable_thinking': False})
        self.assertFalse(payload['stream'])
        self.assertEqual(self.final_bodies, [])

    async def test_count_failure_prevents_any_generation_and_releases_admission(self):
        self.tokenize_status = 503
        response = await self.client.post('/v1/chat/completions', headers={'Authorization': 'Bearer test-key'}, json=self.large_body())
        self.assertEqual(response.status, 503)
        await response.read()
        self.assertEqual([path for path, _, _ in self.requests], ['/tokenize'])
        self.assertFalse(self.gateway.scheduler.busy)
        self.assertEqual(self.gateway.queued, 0)
        self.assertEqual(self.gateway.reserved_bytes, 0)

    async def test_large_request_is_compacted_and_stream_forwarded_with_headers(self):
        body = self.large_body()
        before = copy.deepcopy(body)
        response = await self.client.post('/v1/chat/completions', headers={'Authorization': 'Bearer test-key'}, json=body)
        self.assertEqual(response.status, 200)
        self.assertIn('[DONE]', await response.text())
        self.assertEqual(response.headers['X-Context-Compacted'], 'true')
        self.assertLessEqual(int(response.headers['X-Context-Input-Tokens']), 90000)
        self.assertGreater(int(response.headers['X-Context-Input-Tokens']), 70000)
        self.assertEqual(len(self.final_bodies), 1)
        final = self.final_bodies[0]
        self.assertEqual(final['max_tokens'], 16384)
        self.assertIn(body['messages'][-1], final['messages'])
        self.assertEqual(body, before)
        self.assertEqual(self.gateway.compactions, 1)
        self.assertFalse(self.gateway.scheduler.busy)
        self.assertEqual(self.gateway.reserved_bytes, 0)

    async def test_summary_failure_still_forwards_a_bounded_request(self):
        self.summary_status = 500
        response = await self.client.post('/v1/chat/completions', headers={'Authorization': 'Bearer test-key'}, json=self.large_body())
        self.assertEqual(response.status, 200)
        await response.read()
        self.assertLessEqual(int(response.headers['X-Context-Input-Tokens']), 90000)
        self.assertEqual(response.headers['X-Context-Compacted'], 'true')
        self.assertEqual(len(self.final_bodies), 1)
        self.assertIn('Verify the final image', self.final_bodies[0]['messages'][-1]['content'])

    async def test_context_rejection_retries_before_exposing_stream(self):
        self.context_rejections = 1
        response = await self.client.post('/v1/chat/completions', headers={'Authorization': 'Bearer test-key'}, json=self.large_body())
        self.assertEqual(response.status, 200)
        stream = await response.text()
        self.assertIn('[DONE]', stream)
        self.assertNotIn('Maximum context length', stream)
        self.assertNotIn('input_tokens', stream)
        self.assertEqual(len(self.final_bodies), 2)
        self.assertLess(self.count(self.final_bodies[1]), self.count(self.final_bodies[0]))
        self.assertLessEqual(int(response.headers['X-Context-Input-Tokens']), 80000)
        self.assertFalse(self.gateway.scheduler.busy)
        self.assertEqual(self.gateway.reserved_bytes, 0)

    async def test_old_images_are_removed_while_latest_64_and_input_bytes_survive(self):
        images = [{'type': 'image_url', 'image_url': {'url': f'https://example.test/image-{number}.png'}} for number in range(70)]
        body = {'model': 'qwen3.8-27b', 'messages': [
            {'role': 'user', 'content': images[:35]},
            {'role': 'assistant', 'content': 'First batch inspected'},
            {'role': 'user', 'content': images[35:]},
        ]}
        raw = bytearray(json.dumps(body).encode())
        before = bytes(raw)
        result, info = await self.gateway.prepare_context(raw, 'qwen3.8-27b')
        remaining = [part for message in json.loads(result)['messages'] if isinstance(message.get('content'), list) for part in message['content'] if part.get('type') == 'image_url']
        self.assertEqual(remaining, images[-64:])
        self.assertEqual(bytes(raw), before)
        self.assertEqual(info['omitted_images'], 6)
        self.assertTrue(info['compacted'])
        self.assertTrue(all(len([part for message in payload['messages'] if isinstance(message.get('content'), list) for part in message['content'] if part.get('type') == 'image_url']) == 64 for path, payload, _ in self.requests if path == '/tokenize'))

    async def test_final_count_guard_prevents_generation_if_recount_exceeds_window(self):
        body = {'model': 'qwen3.8-27b', 'messages': [{'role': 'user', 'content': 'Hello'}]}
        with patch.object(self.gateway, 'count_context', AsyncMock(side_effect=[100, 114688])) as counter:
            response = await self.client.post('/v1/chat/completions', headers={'Authorization': 'Bearer test-key'}, json=body)
            self.assertEqual(response.status, 503)
            await response.read()
            self.assertEqual(counter.await_count, 2)
        self.assertEqual(self.final_bodies, [])
        self.assertEqual(self.requests, [])
        self.assertFalse(self.gateway.scheduler.busy)
        self.assertEqual(self.gateway.reserved_bytes, 0)

    async def test_oversized_summary_source_is_not_mutated(self):
        messages = [{'role': 'system', 'content': 'Summarize history'}, {'role': 'user', 'content': 'x' * 130000}]
        before = copy.deepcopy(messages)
        summary = await self.gateway.summarize_context('qwen3.8-27b', messages, 2048)
        self.assertTrue(summary)
        self.assertEqual(messages, before)


if __name__ == '__main__':
    unittest.main()
