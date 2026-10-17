import asyncio
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(os.environ.get('SWITCHER_ROOT', Path(__file__).resolve().parents[1]))
PROFILE_PATH = ROOT / 'charts/llm-switcher/files/profiles.json'
SOURCE_PATH = ROOT / 'charts/llm-switcher/files/server.py'
PROFILES_TEXT = PROFILE_PATH.read_text()
READ_TEXT = Path.read_text


def read_config(path, *args, **kwargs):
    if str(path) == '/config/profiles.json':
        return PROFILES_TEXT
    return READ_TEXT(path, *args, **kwargs)


with patch.dict(os.environ, {'BACKEND_API_KEY': 'test-key'}), patch.object(Path, 'read_text', read_config):
    spec = importlib.util.spec_from_file_location('switcher', SOURCE_PATH)
    switcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(switcher)


class Stream:
    def __init__(self, model, gate):
        self.model = model
        self.gate = gate

    async def iter_any(self):
        yield b'data: {"choices":[]}\n\n'
        if self.model == 'qwen3.8-27b':
            await self.gate.wait()
        yield b'data: [DONE]\n\n'


class Upstream:
    status = 200
    headers = {'Content-Type': 'text/event-stream'}

    def __init__(self, data, gate, bodies, headers):
        self.data = data
        self.gate = gate
        self.bodies = bodies
        self.headers_sent = headers

    async def __aenter__(self):
        raw = bytearray()
        async for chunk in self.data:
            raw.extend(chunk)
        if int(self.headers_sent['Content-Length']) != len(raw):
            raise AssertionError('Content-Length does not match forwarded body')
        body = json.loads(raw)
        self.bodies.append(body)
        self.content = Stream(body['model'], self.gate)
        return self

    async def __aexit__(self, *args):
        pass


class Session:
    def __init__(self, gate):
        self.gate = gate
        self.bodies = []

    def post(self, url, data, **kwargs):
        return Upstream(data, self.gate, self.bodies, kwargs['headers'])


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch.object(switcher.ssl, 'create_default_context', return_value=None):
            self.gateway = switcher.Gateway()
        self.profiles_patch = patch.dict(switcher.PROFILES, {'test-model': {'contextWindow': 128}})
        self.profiles_patch.start()
        self.gateway.scheduler = switcher.ModelScheduler(grace=0.03, quantum=0.2)
        self.calls = []
        self.gate = asyncio.Event()
        self.gateway.session = Session(self.gate)

        async def ensure(name):
            self.calls.append(name)

        self.gateway.ensure_model = ensure
        app = web.Application(client_max_size=switcher.MAX_REQUEST_BYTES, handler_args={'auto_decompress': False})
        app.router.add_route('*', '/{path:.*}', self.gateway.handle)
        self.client = TestClient(TestServer(app, handler_cancellation=True))
        await self.client.start_server()
        self.headers = {'Authorization': 'Bearer test-key'}

    async def asyncTearDown(self):
        self.gate.set()
        await self.client.close()
        self.profiles_patch.stop()

    async def test_catalog_requires_auth_and_lists_configured_models(self):
        response = await self.client.get('/v1/models')
        self.assertEqual(response.status, 401)
        response = await self.client.get('/v1/models', headers=self.headers)
        self.assertEqual({x['id'] for x in (await response.json())['data']}, set(switcher.PROFILES))
        self.assertEqual(self.calls, [])

    async def test_invalid_model_cannot_patch_deployment(self):
        for model in ['unknown', ['test-model']]:
            response = await self.client.post('/v1/chat/completions', headers=self.headers, json={'model': model})
            self.assertEqual(response.status, 404)
        self.assertEqual(self.calls, [])

    async def test_switch_waits_until_previous_stream_finishes(self):
        first = await self.client.post('/v1/chat/completions', headers=self.headers, json={'model': 'qwen3.8-27b'})
        second_task = asyncio.create_task(self.client.post('/v1/chat/completions', headers=self.headers, json={'model': 'test-model'}))
        await asyncio.sleep(0.05)
        self.assertEqual(self.calls, ['qwen3.8-27b'])
        self.assertFalse(second_task.done())
        self.gate.set()
        self.assertIn('[DONE]', await first.text())
        second = await second_task
        self.assertIn('[DONE]', await second.text())
        self.assertEqual(self.calls, ['qwen3.8-27b', 'test-model'])

    async def test_model_startup_failure_releases_queue(self):
        async def fail(name):
            raise RuntimeError('startup failed')
        self.gateway.ensure_model = fail
        response = await self.client.post('/v1/chat/completions', headers=self.headers, json={'model': 'test-model'})
        self.assertEqual(response.status, 503)
        self.assertEqual(self.gateway.queued, 0)
        self.assertFalse(self.gateway.scheduler.busy)
        self.assertEqual(self.gateway.reserved_bytes, 0)

    async def wait_for_idle(self):
        async with asyncio.timeout(2):
            while self.gateway.queued:
                await asyncio.sleep(0.01)
        self.assertEqual(self.gateway.reserved_bytes, 0)

    async def test_image_request_larger_than_old_four_mib_limit_reaches_upstream(self):
        body = {'model': 'test-model', 'messages': [{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + 'A' * (5 * 1024 * 1024)}}
        ]}]}
        response = await self.client.post('/v1/chat/completions', headers=self.headers, json=body)
        self.assertEqual(response.status, 200)
        self.assertIn('[DONE]', await response.text())
        self.assertEqual(self.gateway.session.bodies, [body])
        await self.wait_for_idle()

    async def test_oversized_and_compressed_requests_are_rejected_without_startup(self):
        with patch.object(switcher, 'MAX_REQUEST_BYTES', 64):
            response = await self.client.post('/v1/chat/completions', headers=self.headers, data=b'x' * 65)
            self.assertEqual(response.status, 413)
        response = await self.client.post('/v1/chat/completions', headers={**self.headers, 'Content-Encoding': 'gzip'}, data=b'compressed')
        self.assertEqual(response.status, 415)
        self.assertEqual(self.calls, [])
        await self.wait_for_idle()

    async def test_invalid_json_releases_admission(self):
        response = await self.client.post('/v1/chat/completions', headers=self.headers, data=b'{')
        self.assertEqual(response.status, 400)
        self.assertEqual(self.calls, [])
        await self.wait_for_idle()

    async def test_stream_holds_aggregate_budget_until_finished(self):
        body = json.dumps({'model': 'qwen3.8-27b'}).encode()
        with patch.object(switcher, 'MAX_RESERVED_BYTES', len(body)):
            first = await self.client.post('/v1/chat/completions', headers=self.headers, data=body)
            self.assertEqual(first.status, 200)
            self.assertEqual(self.gateway.reserved_bytes, len(body))
            second = await self.client.post('/v1/chat/completions', headers=self.headers, data=body)
            self.assertEqual(second.status, 429)
            self.gate.set()
            await first.read()
            await self.wait_for_idle()
            third = await self.client.post('/v1/chat/completions', headers=self.headers, data=body)
            self.assertEqual(third.status, 200)
            await third.read()
        await self.wait_for_idle()

    async def test_chunked_request_reserves_maximum_until_stream_finishes(self):
        async def chunks():
            yield b'{"model":'
            yield b'"qwen3.8-27b"}'
        with patch.object(switcher, 'MAX_REQUEST_BYTES', 128), patch.object(switcher, 'MAX_RESERVED_BYTES', 128):
            first = await self.client.post('/v1/chat/completions', headers=self.headers, data=chunks())
            self.assertEqual(first.status, 200)
            self.assertEqual(self.gateway.reserved_bytes, 128)
            second = await self.client.post('/v1/chat/completions', headers=self.headers, json={'model': 'test-model'})
            self.assertEqual(second.status, 429)
            self.gate.set()
            await first.read()
        await self.wait_for_idle()

    async def test_chunked_oversize_releases_reservation(self):
        async def chunks():
            yield b'x' * 33
            yield b'x' * 32
        with patch.object(switcher, 'MAX_REQUEST_BYTES', 64):
            response = await self.client.post('/v1/chat/completions', headers=self.headers, data=chunks())
            self.assertEqual(response.status, 413)
        self.assertEqual(self.calls, [])
        await self.wait_for_idle()

    async def test_disconnect_releases_stream_reservation_and_gpu_slot(self):
        response = await self.client.post('/v1/chat/completions', headers=self.headers, json={'model': 'qwen3.8-27b'})
        self.assertEqual(response.status, 200)
        self.assertGreater(self.gateway.reserved_bytes, 0)
        response.close()
        await self.wait_for_idle()
        self.assertFalse(self.gateway.scheduler.busy)

    async def test_disconnected_upload_releases_admission(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_body():
            yield b'{'
            entered.set()
            await release.wait()
            yield b'}'

        upload = asyncio.create_task(self.client.post('/v1/chat/completions', headers=self.headers, data=slow_body()))
        await entered.wait()
        async with asyncio.timeout(2):
            while self.gateway.queued != 1:
                await asyncio.sleep(0.01)
        upload.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await upload
        await self.wait_for_idle()
        self.assertEqual(self.calls, [])

    async def test_upload_timeout_releases_admission(self):
        release = asyncio.Event()

        async def slow_body():
            yield b'{'
            await release.wait()
            yield b'}'

        try:
            with patch.object(switcher, 'BODY_READ_TIMEOUT', 0.03):
                async with asyncio.timeout(2):
                    response = await self.client.post('/v1/chat/completions', headers=self.headers, data=slow_body())
                self.assertEqual(response.status, 408)
                await response.read()
            await self.wait_for_idle()
            self.assertEqual(self.calls, [])
        finally:
            release.set()

    async def test_handler_limit_rejects_before_reading_body(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_body():
            yield b'{'
            entered.set()
            await release.wait()
            yield b'"model":"test-model"}'

        with patch.object(switcher, 'MAX_HANDLERS', 1), patch.object(switcher, 'MAX_RESERVED_BYTES', 2 * switcher.MAX_REQUEST_BYTES):
            first = asyncio.create_task(self.client.post('/v1/chat/completions', headers=self.headers, data=slow_body()))
            await entered.wait()
            async with asyncio.timeout(2):
                while self.gateway.queued != 1:
                    await asyncio.sleep(0.01)
            try:
                second = await self.client.post('/v1/chat/completions', headers=self.headers, json={'model': 'test-model'})
                self.assertEqual(second.status, 429)
                self.assertEqual(self.calls, [])
            finally:
                release.set()
            response = await first
            self.assertEqual(response.status, 200)
            await response.read()
        await self.wait_for_idle()


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_continuation_precedes_other_model_during_grace(self):
        scheduler = switcher.ModelScheduler(grace=0.08, quantum=1)
        order = []
        async with scheduler.slot('a'):
            scheduler.loaded()

        async def run(model):
            async with scheduler.slot(model):
                scheduler.loaded()
                order.append(model)

        other = asyncio.create_task(run('b'))
        await asyncio.sleep(0.01)
        await run('a')
        self.assertEqual(order, ['a'])
        await other
        self.assertEqual(order, ['a', 'b'])

    async def test_time_quantum_prevents_starvation(self):
        scheduler = switcher.ModelScheduler(grace=1, quantum=0.01)
        order = []
        async def run(model):
            async with scheduler.slot(model):
                scheduler.loaded()
                order.append(model)
        async with scheduler.slot('a'):
            scheduler.loaded()
            other = asyncio.create_task(run('b'))
            continuation = asyncio.create_task(run('a'))
            await asyncio.sleep(0.02)
        await other
        scheduler.idle_until = 0
        await continuation
        self.assertEqual(order, ['b', 'a'])

    async def test_cancelled_waiter_does_not_take_gpu_slot(self):
        scheduler = switcher.ModelScheduler(grace=0)
        async def wait():
            async with scheduler.slot('b'):
                self.fail('Cancelled waiter acquired a slot')
        async with scheduler.slot('a'):
            task = asyncio.create_task(wait())
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(scheduler.waiting, [])
        self.assertFalse(scheduler.busy)

    async def test_expired_waiter_is_removed_without_interrupting_active_request(self):
        scheduler = switcher.ModelScheduler(grace=0)
        async with scheduler.slot('a'):
            with self.assertRaises(TimeoutError):
                async with scheduler.slot('b', timeout=0.01):
                    self.fail('Waiting request overtook active inference')
            self.assertTrue(scheduler.busy)
            self.assertEqual(scheduler.waiting, [])


if __name__ == '__main__':
    unittest.main()
