import asyncio
import copy
import hashlib
import hmac
import json
import logging
import os
import ssl
import time
import uuid
from contextlib import asynccontextmanager
from collections import OrderedDict
from pathlib import Path

from aiohttp import ClientError, ClientSession, ClientTimeout, web
from context_budget import compact_chat

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
        self.summary_cache = OrderedDict()
        self.compactions = 0
        self.kube_ssl = ssl.create_default_context(cafile=CA)

    async def count_context(self, body):
        fields = ('model', 'messages', 'tools', 'chat_template', 'chat_template_kwargs', 'media_io_kwargs', 'mm_processor_kwargs', 'add_generation_prompt', 'continue_final_message', 'add_special_tokens')
        payload = {key: body[key] for key in fields if key in body}
        kwargs = dict(payload.get('chat_template_kwargs') or {})
        for key in ('documents', 'reasoning_effort'):
            if body.get(key) is not None and body[key] != 'auto':
                kwargs[key] = body[key]
        if body.get('reasoning_effort') is not None and 'enable_thinking' not in kwargs:
            kwargs['enable_thinking'] = body['reasoning_effort'] != 'none'
        payload['chat_template_kwargs'] = kwargs
        async with self.session.post(BACKEND + '/tokenize', json=payload, headers={'Authorization': 'Bearer ' + KEY}, timeout=ClientTimeout(total=120)) as response:
            if response.status != 200:
                LOG.error('backend_tokenization_failed model=%s status=%s', body.get('model'), response.status)
                raise RuntimeError('Backend tokenization failed: ' + str(response.status))
            result = await response.json()
        return int(result['count'])

    async def summarize_context(self, model, messages, max_tokens):
        key = hashlib.sha256(json.dumps([model, messages, max_tokens], sort_keys=True).encode()).hexdigest()
        cached = self.summary_cache.get(key)
        if cached and time.monotonic() - cached[0] < 600:
            self.summary_cache.move_to_end(key)
            return cached[1]
        body = {'model': model, 'messages': copy.deepcopy(messages), 'max_tokens': max_tokens, 'temperature': 0.1, 'stream': False, 'chat_template_kwargs': {'enable_thinking': False}}
        while await self.count_context(body) + max_tokens + 512 > PROFILES[model]['contextWindow']:
            text = body['messages'][-1]['content']
            if len(text) < 128:
                raise ValueError('Summary instructions exceed the context window')
            body['messages'][-1] = {**body['messages'][-1], 'content': text[:len(text) // 4] + '\n[Middle omitted]\n' + text[-len(text) // 4:]}
        async with self.session.post(BACKEND + '/v1/chat/completions', json=body, headers={'Authorization': 'Bearer ' + KEY}, timeout=ClientTimeout(total=180)) as response:
            if response.status != 200:
                raise RuntimeError('Context summarization failed: ' + str(response.status))
            result = await response.json()
        summary = result['choices'][0]['message'].get('content')
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError('Empty context summary')
        self.summary_cache[key] = time.monotonic(), summary
        self.summary_cache.move_to_end(key)
        while len(self.summary_cache) > 16:
            self.summary_cache.popitem(last=False)
        return summary

    async def prepare_context(self, raw, model, force=False, context_window=None):
        body = json.loads(raw)
        if not isinstance(body.get('messages'), list):
            return raw, {}
        body.pop('kv_transfer_params', None)
        image_parts = [(message, index) for message in body['messages'] if isinstance(message.get('content'), list) for index, part in enumerate(message['content']) if isinstance(part, dict) and part.get('type') in ('image_url', 'input_image')]
        omitted_images = max(0, len(image_parts) - 64)
        for message, index in image_parts[:omitted_images]:
            message['content'][index] = {'type': 'text', 'text': '[Older image omitted from active context]'}
        if body.get('max_completion_tokens') is None and body.get('max_tokens') is None:
            body['max_tokens'] = 16384
        window = context_window or PROFILES[model]['contextWindow']
        async def summarize(messages, maximum):
            return await self.summarize_context(model, messages, maximum)
        result, info = await compact_chat(body, window, self.count_context, summarize, force=force)
        final_tokens = await self.count_context(result)
        reserve = int(result.get('max_completion_tokens') or result.get('max_tokens') or 16384)
        if final_tokens + reserve > window:
            raise ValueError('Context budget verification failed')
        info['input_tokens'] = final_tokens
        if omitted_images:
            info['compacted'] = True
            info['omitted_images'] = omitted_images
        if info.get('compacted'):
            self.compactions += 1
            LOG.info('compacted model=%s input_tokens=%s target=%s summary=%s images_removed=%s', model, final_tokens, info['target_tokens'], info['summary_used'], info.get('removed_images', 0) + omitted_images)
        return bytearray(json.dumps(result).encode()), info

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
            return web.json_response({'loaded_model': self.active, 'running': self.scheduler.busy, 'waiting': counts, 'reserved_bytes': self.reserved_bytes, 'receiving': self.receiving, 'in_flight': self.queued, 'context_compactions': self.compactions})
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
        stage = 'queue'
        request_id = str(uuid.uuid4())
        LOG.info('queued request=%s model=%s in_flight=%s', request_id, model, self.queued)
        try:
            async with self.scheduler.slot(model) as waited:
                async with asyncio.timeout(1800):
                    LOG.info('admitted request=%s model=%s waited=%.1fs', request_id, model, waited)
                    stage = 'model_readiness'
                    await self.ensure_model(model)
                    self.scheduler.loaded()
                    context_info = {}
                    if request.path == '/v1/chat/completions':
                        stage = 'context_preparation'
                        raw, context_info = await self.prepare_context(raw, model)
                    stage = 'inference'
                    sampling = {key: value for key, value in json.loads(raw).items() if key in ('temperature', 'top_p', 'top_k', 'min_p', 'presence_penalty', 'frequency_penalty', 'repetition_penalty', 'max_tokens', 'max_completion_tokens') and isinstance(value, (int, float)) and not isinstance(value, bool)}
                    LOG.info('sampling request=%s model=%s values=%s', request_id, model, json.dumps(sampling, sort_keys=True))
                    for attempt in range(3):
                        async with self.session.post(BACKEND + request.path, data=body_chunks(raw), headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json', 'Content-Length': str(len(raw))}, timeout=ClientTimeout(total=None, sock_connect=10, sock_read=1800)) as upstream:
                            rejected = None
                            if upstream.status == 400 and context_info:
                                rejected = await upstream.read()
                                message = rejected.decode('utf-8', 'replace').lower()
                                if any(marker in message for marker in ('maximum context length', 'context length exceeded', 'input_tokens')):
                                    if attempt == 2:
                                        raise RuntimeError('Backend rejected the verified context budget')
                                    reserve = context_info['output_reserve']
                                    window = min(PROFILES[model]['contextWindow'], reserve + 512 + 80000 - attempt * 10000)
                                    raw, context_info = await self.prepare_context(raw, model, force=True, context_window=window)
                                    continue
                            response = web.StreamResponse(status=upstream.status, headers={'Content-Type': upstream.headers.get('Content-Type', 'application/json'), 'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
                            if context_info:
                                response.headers['X-Context-Input-Tokens'] = str(context_info['input_tokens'])
                                response.headers['X-Context-Compacted'] = str(context_info.get('compacted', False)).lower()
                            await response.prepare(request)
                            if rejected is not None:
                                await response.write(rejected)
                            else:
                                async for chunk in upstream.content.iter_any():
                                    await response.write(chunk)
                            await response.write_eof()
                            LOG.info('finished request=%s model=%s status=%s', request_id, model, upstream.status)
                            return response
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.error('request=%s model=%s stage=%s failed=%s', request_id, model, stage, type(exc).__name__)
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
