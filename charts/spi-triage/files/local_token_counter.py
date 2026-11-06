"""Offline, deliberately narrow Qwen text accounting. Never downloads assets."""
import hashlib
import importlib.metadata
import json
import os
import threading
from pathlib import Path
from core import Failure

PINS = {
    'tokenizer.json': '06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523',
    'chat_template.jinja': 'c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041',
    'tokenizer_config.json': '5f7aa0d810000c4a0940b35c8f16e56c3439260fccc13a321826ebc3ccf2501f',
}
MAX_BYTES = 512 * 1024
_INITIALIZE = threading.Lock()
_ENCODE = threading.Lock()
_NATIVE = None
_IDENTITY = None


def contract(body):
    messages = body.get('messages', [])
    if (body.get('model') != 'qwen3.8-27b' or
        [m.get('role') for m in messages] != ['system', 'user'] or
        any(set(m) != {'role', 'content'} or not isinstance(m['content'], str) for m in messages) or
        body.get('chat_template_kwargs') != {'enable_thinking': False} or
        'tools' in body or body.get('max_tokens') not in (768, 2500)):
        raise Failure('LLM_ACCOUNTING_CONTRACT_MISMATCH')
    return messages


def render(body):
    messages = contract(body)
    # Bound before trimming, concatenating, normalizing or entering Rust BPE.
    if any(len(m['content']) > MAX_BYTES for m in messages):
        raise Failure('LLM_REQUEST_TOO_LARGE')
    if sum(len(m['content'].encode('utf-8')) for m in messages) + 128 > MAX_BYTES:
        raise Failure('LLM_REQUEST_TOO_LARGE')
    system, user = (m['content'].strip() for m in messages)
    return (('<|im_start|>system\n' + system + '<|im_end|>\n') if system else '') + \
        '<|im_start|>user\n' + user + '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


class LocalCounter:
    def __init__(self, root='/opt/spi-tokenizer'):
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        os.environ['RAYON_NUM_THREADS'] = '1'
        root = Path(root).resolve()
        try:
            with _INITIALIZE:
                self._validated_load(root)
        except Exception:
            raise Failure('LLM_LOCAL_COUNTER_INVALID') from None

    def _validated_load(self, root):
        global _NATIVE, _IDENTITY
        try:
            for name, expected in PINS.items():
                with (root / name).open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                        raise ValueError('asset hash')
            if importlib.metadata.version('tokenizers') != '0.22.2':
                raise ValueError('library version')
            # Build manifest pins every installed library file; reject runtime drift.
            manifest = json.loads((root / 'library-hashes.json').read_text())
            if not manifest:
                raise ValueError('empty library manifest')
            for path, expected in manifest.items():
                with Path(path).open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                        raise ValueError('library hash')
            identity = (str(root), tuple(sorted(manifest.items())), tuple(sorted(PINS.items())))
            if _NATIVE is not None:
                if identity != _IDENTITY:
                    raise ValueError('restart required for different contract')
            else:
                from tokenizers import Tokenizer
                native = Tokenizer.from_file(str(root / 'tokenizer.json'))
                _IDENTITY = identity
                _NATIVE = native
            self._tokenizer = _NATIVE
        except Exception:
            raise Failure('LLM_LOCAL_COUNTER_INVALID') from None

    @property
    def tokenizer(self):
        return self._tokenizer

    def reservation(self, body):
        prompt = render(body)
        schema = json.dumps(body['response_format'], ensure_ascii=False).encode('utf-8')
        if len(schema) > MAX_BYTES:
            raise Failure('LLM_REQUEST_TOO_LARGE')
        with _ENCODE:
            count = len(self._tokenizer.encode(prompt, add_special_tokens=False).ids)
        return count + len(schema) + 256 + body['max_tokens']


def configured_counter():
    mode = os.environ.get('SPI_TOKEN_ACCOUNTING_MODE', 'byte-bound-v1')
    if mode == 'byte-bound-v1':
        return None
    if mode == 'local-qwen-v1':
        return LocalCounter()
    raise Failure('LLM_ACCOUNTING_MODE_INVALID')
