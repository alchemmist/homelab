import asyncio
import hashlib
import hmac
import json
import logging
import os
import ssl
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from aiohttp import ClientError, ClientSession, ClientTimeout, web

LOG = logging.getLogger('llm-switcher')
PROFILES = json.loads(Path('/config/profiles.json').read_text())
KEY = os.environ['BACKEND_API_KEY']
BACKEND = 'http://vllm.llm.svc.cluster.local:8000'
KUBE = 'https://kubernetes.default.svc'
DEPLOYMENT = '/apis/apps/v1/namespaces/llm/deployments/vllm'
TOKEN = Path('/var/run/secrets/kubernetes.io/serviceaccount/token')
CA = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_RESERVED_BYTES = 64 * 1024 * 1024
MAX_HANDLERS = 32
BODY_READ_TIMEOUT = 60
BODY_CHUNK_BYTES = 64 * 1024


def error(message, status):
    return web.json_response({'error': {'message': message, 'type': 'gateway_error', 'code': status}}, status=status)


async def body_chunks(raw):
    view = memoryview(raw)
    for offset in range(0, len(view), BODY_CHUNK_BYTES):
        yield view[offset:offset + BODY_CHUNK_BYTES]


def model_args(profile):
    return [profile['model'], '--revision', profile['revision'], '--tokenizer-revision', profile['revision'], '--served-model-name', profile['servedModelName'], '--host', '0.0.0.0', '--port', '8000', *profile['args']]


class ModelScheduler:
    def __init__(self, grace=90, quantum=600):
        self.condition = asyncio.Condition()
        self.waiting = []
        self.busy = False
        self.model = None
        self.started = None
        self.idle_until = 0
        self.grace = grace
        self.quantum = quantum

    def candidate(self):
        now = time.monotonic()
        same = [t for t in self.waiting if t['model'] == self.model]
        other = [t for t in self.waiting if t['model'] != self.model]
        if other and self.started is not None and now - self.started >= self.quantum:
            return other[0]
        if same:
            return same[0]
        if other and now >= self.idle_until:
            return other[0]
        return None

    def loaded(self):
        if self.started is None:
            self.started = time.monotonic()

    @asynccontextmanager
    async def slot(self, model, timeout=5400):
        ticket = {'model': model, 'enqueued': time.monotonic()}
        async with self.condition:
            self.waiting.append(ticket)
            self.condition.notify_all()
            try:
                async with asyncio.timeout(timeout):
                    while self.busy or self.candidate() is not ticket:
                        delay = max(0.01, self.idle_until - time.monotonic()) if not self.busy else 1
                        try:
                            await asyncio.wait_for(self.condition.wait(), min(delay, 1))
                        except TimeoutError:
                            pass
                self.waiting.remove(ticket)
                self.busy = True
                if self.model != model:
                    self.model = model
                    self.started = None
            except BaseException:
                if ticket in self.waiting:
                    self.waiting.remove(ticket)
                self.condition.notify_all()
                raise
        failed = False
        try:
            yield time.monotonic() - ticket['enqueued']
        except BaseException:
            failed = True
            raise
        finally:
            async with self.condition:
                self.busy = False
                self.idle_until = time.monotonic() + (0 if failed else self.grace)
                if failed and self.started is None:
                    self.model = None
                self.condition.notify_all()


class Gateway:
    def __init__(self):
        self.scheduler = ModelScheduler()
        self.queued = 0
        self.reserved_bytes = 0
        self.receiving = 0
        self.active = None
        self.session = None
        self.kube_ssl = ssl.create_default_context(cafile=CA)

    async def kube(self, method, data=None):
        headers = {'Authorization': 'Bearer ' + TOKEN.read_text().strip()}
        if data is not None:
            headers['Content-Type'] = 'application/strategic-merge-patch+json'
        async with self.session.request(method, KUBE + DEPLOYMENT, json=data, headers=headers, ssl=self.kube_ssl, timeout=ClientTimeout(total=30)) as response:
            if response.status >= 300:
                raise RuntimeError('Kubernetes deployment request failed: ' + str(response.status))
            return await response.json()

    async def loaded_model(self):
        try:
            async with self.session.get(BACKEND + '/v1/models', headers={'Authorization': 'Bearer ' + KEY}, timeout=ClientTimeout(total=3)) as response:
                if response.status == 200:
                    return {m['id'] for m in (await response.json()).get('data', [])}
        except (ClientError, OSError, ValueError, asyncio.TimeoutError):
            pass
        return set()

    async def ensure_model(self, name):
        args = model_args(PROFILES[name])
        deployment = await self.kube('GET')
        container = next(c for c in deployment['spec']['template']['spec']['containers'] if c['name'] == 'vllm')
        if container.get('args') != args:
            LOG.info('switching model to %s', name)
            deployment = await self.kube('PATCH', {'spec': {'template': {'metadata': {'annotations': {'llm.homelab/model-profile': hashlib.sha256(json.dumps(args).encode()).hexdigest()}}, 'spec': {'containers': [{'name': 'vllm', 'args': args}]}}}})
        generation = deployment['metadata']['generation']
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            deployment = await self.kube('GET')
            status = deployment.get('status', {})
            ready = status.get('observedGeneration', 0) >= generation and status.get('updatedReplicas', 0) == 1 and status.get('availableReplicas', 0) == 1
            if ready and name in await self.loaded_model():
                self.active = name
                return
            await asyncio.sleep(2)
        raise TimeoutError('Model did not become ready within 600 seconds')

    async def handle(self, request):
        if request.path == '/health':
            return web.json_response({'status': 'ok'})
        if not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + KEY):
            return error('Invalid API key', 401)
        if request.path == '/status' and request.method == 'GET':
            counts = {name: sum(t['model'] == name for t in self.scheduler.waiting) for name in PROFILES}
            return web.json_response({'loaded_model': self.active, 'running': self.scheduler.busy, 'waiting': counts, 'reserved_bytes': self.reserved_bytes, 'receiving': self.receiving, 'in_flight': self.queued})
        if request.path == '/v1/models' and request.method == 'GET':
            return web.json_response({'object': 'list', 'data': [{'id': name, 'object': 'model', 'created': 0, 'owned_by': 'socrat', 'max_model_len': p['contextWindow']} for name, p in PROFILES.items()]})
        if request.path not in ['/v1/chat/completions', '/v1/completions', '/v1/responses'] or request.method != 'POST':
            return error('Unsupported endpoint', 404)
        if request.headers.get('Content-Encoding', 'identity').strip().lower() != 'identity':
            return error('Compressed request bodies are not supported', 415)
        reserved = request.content_length if request.content_length is not None else MAX_REQUEST_BYTES
        if reserved > MAX_REQUEST_BYTES:
            return error('Request body exceeds the 64 MiB limit', 413)
        if self.queued >= MAX_HANDLERS or self.reserved_bytes + reserved > MAX_RESERVED_BYTES:
            return error('Model queue or request body budget is full; retry later', 429)
        self.queued += 1
        self.reserved_bytes += reserved
        try:
            self.receiving += 1
            raw = bytearray()
            try:
                async with asyncio.timeout(BODY_READ_TIMEOUT):
                    async for chunk in request.content.iter_chunked(BODY_CHUNK_BYTES):
                        if len(raw) + len(chunk) > reserved:
                            return error('Request body exceeds its reserved size', 413)
                        raw.extend(chunk)
                body = json.loads(raw)
            except TimeoutError:
                return error('Request body read timed out', 408)
            except (ValueError, UnicodeError):
                return error('Invalid JSON', 400)
            except (ClientError, OSError):
                return error('Request body could not be read', 400)
            finally:
                self.receiving -= 1
            if not isinstance(body, dict) or not isinstance(body.get('model'), str) or body['model'] not in PROFILES:
                return error('Unknown model', 404)
            if body.get('background'):
                return error('Background responses are not supported by the model switcher', 400)
            model = body['model']
            del body
            return await self.forward(request, raw, model)
        finally:
            self.queued -= 1
            self.reserved_bytes -= reserved

    async def forward(self, request, raw, model):
        response = None
        request_id = str(uuid.uuid4())
        LOG.info('queued request=%s model=%s in_flight=%s', request_id, model, self.queued)
        try:
            async with self.scheduler.slot(model) as waited:
                async with asyncio.timeout(1800):
                    LOG.info('admitted request=%s model=%s waited=%.1fs', request_id, model, waited)
                    await self.ensure_model(model)
                    self.scheduler.loaded()
                    async with self.session.post(BACKEND + request.path, data=body_chunks(raw), headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json', 'Content-Length': str(len(raw))}, timeout=ClientTimeout(total=None, sock_connect=10, sock_read=1800)) as upstream:
                        response = web.StreamResponse(status=upstream.status, headers={'Content-Type': upstream.headers.get('Content-Type', 'application/json'), 'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
                        await response.prepare(request)
                        async for chunk in upstream.content.iter_any():
                            await response.write(chunk)
                        await response.write_eof()
                        LOG.info('finished request=%s model=%s status=%s', request_id, model, upstream.status)
                        return response
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.error('request=%s model=%s failed=%s', request_id, model, type(exc).__name__)
            if response is not None and response.prepared:
                response.force_close()
                return response
            return error('Model startup or inference failed; retry later', 503)

    async def start(self, app):
        self.session = ClientSession()

    async def stop(self, app):
        await self.session.close()


def main():
    logging.basicConfig(level=logging.INFO)
    gateway = Gateway()
    app = web.Application(client_max_size=MAX_REQUEST_BYTES, handler_args={'auto_decompress': False})
    app.router.add_route('*', '/{path:.*}', gateway.handle)
    app.on_startup.append(gateway.start)
    app.on_cleanup.append(gateway.stop)
    web.run_app(app, host='0.0.0.0', port=8000, handler_cancellation=True, shutdown_timeout=1800, access_log=None)


if __name__ == '__main__':
    main()
