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

    def __init__(self, model, gate):
        self.content = Stream(model, gate)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class Session:
    def __init__(self, gate):
        self.gate = gate

    def post(self, url, json, **kwargs):
        return Upstream(json['model'], self.gate)


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
        app = web.Application()
        app.router.add_route('*', '/{path:.*}', self.gateway.handle)
        self.client = TestClient(TestServer(app))
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
