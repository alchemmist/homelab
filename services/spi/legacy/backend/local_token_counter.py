"""Offline, deliberately narrow Qwen text accounting. Never downloads assets."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from core import Failure

if TYPE_CHECKING:
    from tokenizers import Tokenizer

PINS: dict[str, str] = {
    "tokenizer.json": "06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523",
    "chat_template.jinja": "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041",
    "tokenizer_config.json": "5f7aa0d810000c4a0940b35c8f16e56c3439260fccc13a321826ebc3ccf2501f",
}
MAX_BYTES = 512 * 1024
MODEL_NAME = "qwen3.8-27b"
ALLOWED_MAX_TOKENS = (768, 2500)
REQUEST_KEYS = {
    "model",
    "messages",
    "chat_template_kwargs",
    "max_tokens",
    "response_format",
    "temperature",
}
JSON_DEPTH_LIMIT = 64
JSON_BRACE_OVERHEAD = 2
JSON_DICT_ENTRY_COST = 4
JSON_LIST_ITEM_COST = 2
JSON_SCALAR_COST = 32
JSON_CONTROL_CODE_MAX = 32
JSON_ESCAPED_CODEPOINTS = (34, 92)
JSON_SCALAR_BITS_LIMIT = 64
RENDER_PAD_BYTES = 128
PROXY_EXTRA_CHARS = 3
PROXY_CHARS_PER_TOKEN = 4
PROXY_FLOOR_FRAMING = 256
FULL_BUDGET_RESERVATION = 30001
CODE_ACCOUNTING_MISMATCH = "LLM_ACCOUNTING_CONTRACT_MISMATCH"
CODE_REQUEST_TOO_LARGE = "LLM_REQUEST_TOO_LARGE"
CODE_COUNTER_INVALID = "LLM_LOCAL_COUNTER_INVALID"
CODE_MODE_INVALID = "LLM_ACCOUNTING_MODE_INVALID"
REASON_ASSET_HASH = "asset hash"
REASON_LIBRARY_VERSION = "library version"
REASON_LIBRARY_HASH = "library hash"
REASON_EMPTY_MANIFEST = "empty library manifest"
REASON_RESTART_REQUIRED = "restart required for different contract"

_Identity = tuple[str, tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]
_INITIALIZE = threading.Lock()
_ENCODE = threading.Lock()


class _Message(TypedDict):
    role: str
    content: str


class _NativeMemo:
    tokenizer: Tokenizer | None = None
    identity: _Identity | None = None


_RUNTIME = _NativeMemo()


def contract(body: object) -> list[_Message]:
    """Reject any body outside the reviewed two-message accounting contract."""
    if not isinstance(body, dict) or set(body) - REQUEST_KEYS:
        raise Failure(CODE_ACCOUNTING_MISMATCH)
    untyped = body.get("messages", [])
    if not isinstance(untyped, list) or any(not isinstance(item, dict) for item in untyped):
        raise Failure(CODE_ACCOUNTING_MISMATCH)
    messages = [cast("dict[str, object]", item) for item in untyped]
    if (
        body.get("model") != MODEL_NAME
        or [item.get("role") for item in messages] != ["system", "user"]
        or any(
            set(item) != {"role", "content"} or not isinstance(item["content"], str)
            for item in messages
        )
        or (
            body.get("chat_template_kwargs") != {"enable_thinking": False}
            or cast("dict[str, object]", body["chat_template_kwargs"]).get("enable_thinking")
            is not False
        )
        or "tools" in body
        or body.get("max_tokens") not in ALLOWED_MAX_TOKENS
    ):
        raise Failure(CODE_ACCOUNTING_MISMATCH)
    return cast("list[_Message]", untyped)


def render(body: object) -> str:
    """Render one validated body into the pinned chat template framing."""
    messages = contract(body)
    # Bound before trimming, concatenating, normalizing or entering Rust BPE.
    if any(len(message["content"]) > MAX_BYTES for message in messages):
        raise Failure(CODE_REQUEST_TOO_LARGE)
    if (
        sum(len(message["content"].encode("utf-8")) for message in messages) + RENDER_PAD_BYTES
        > MAX_BYTES
    ):
        raise Failure(CODE_REQUEST_TOO_LARGE)
    system, user = (message["content"].strip() for message in messages)
    return (
        (("<|im_start|>system\n" + system + "<|im_end|>\n") if system else "")
        + "<|im_start|>user\n"
        + user
        + "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def raw_fits(body: object) -> bool:
    """Bound counter JSON work before serialization, trimming or native encoding.

    Charge bounded UTF-8 plus JSON escaping, containers
    and scalar spelling. Traversal stops at the budget; no unbounded encode.
    This intentionally conservative guard is separate from token accounting.
    """
    remaining = MAX_BYTES
    stack: list[tuple[object, int]] = [(body, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > JSON_DEPTH_LIMIT:
            raise Failure(CODE_ACCOUNTING_MISMATCH)
        if isinstance(value, str):
            if len(value) > MAX_BYTES:
                return False
            remaining -= (
                len(value.encode("utf-8"))
                + JSON_BRACE_OVERHEAD
                + sum(
                    5
                    if ord(char) < JSON_CONTROL_CODE_MAX
                    else 1
                    if ord(char) in JSON_ESCAPED_CODEPOINTS
                    else 0
                    for char in value
                )
            )
        elif isinstance(value, dict):
            remaining -= JSON_BRACE_OVERHEAD + JSON_DICT_ENTRY_COST * len(value)
            if remaining < 0:
                return False
            for key, item in value.items():
                if not isinstance(key, str):
                    raise Failure(CODE_ACCOUNTING_MISMATCH)
                stack.extend(((key, depth + 1), (item, depth + 1)))
        elif isinstance(value, list):
            remaining -= JSON_BRACE_OVERHEAD + JSON_LIST_ITEM_COST * len(value)
            if remaining < 0:
                return False
            stack.extend((item, depth + 1) for item in value)
        elif (
            value is None
            or isinstance(value, (bool, float))
            or (isinstance(value, int) and value.bit_length() < JSON_SCALAR_BITS_LIMIT)
        ):
            remaining -= JSON_SCALAR_COST
        else:
            raise Failure(CODE_ACCOUNTING_MISMATCH)
        if remaining < 0:
            return False
    return True


def _verified_library_manifest(root: Path) -> dict[str, str]:
    """Load the deployed manifest and hash-check every installed library file."""
    manifest = cast("dict[str, str]", json.loads((root / "library-hashes.json").read_text()))
    if not manifest:
        raise ValueError(REASON_EMPTY_MANIFEST)
    for path, expected in manifest.items():
        with Path(path).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError(REASON_LIBRARY_HASH)
    return manifest


def _install_native(root: Path, identity: _Identity) -> Tokenizer:
    """Build the native tokenizer once and memoize it with its identity."""
    from tokenizers import Tokenizer

    native = Tokenizer.from_file(str(root / "tokenizer.json"))
    _RUNTIME.identity = identity
    _RUNTIME.tokenizer = native
    return native


class LocalCounter:
    """Byte- and token-accounting facade over the digest-pinned native tokenizer."""

    def __init__(self, root: str = "/opt/spi-tokenizer") -> None:
        """Force single-threaded native execution before validating pinned assets."""
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["RAYON_NUM_THREADS"] = "1"
        base = Path(root).resolve()
        try:
            with _INITIALIZE:
                self._validated_load(base)
        except Exception:
            raise Failure(CODE_COUNTER_INVALID) from None

    def _validated_load(self, root: Path) -> None:
        """Validate every pinned asset before memoizing the native tokenizer."""
        for name, expected in PINS.items():
            with (root / name).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError(REASON_ASSET_HASH)
        if importlib.metadata.version("tokenizers") != "0.22.2":
            raise ValueError(REASON_LIBRARY_VERSION)
        manifest = _verified_library_manifest(root)
        identity = (
            str(root),
            tuple(sorted(manifest.items())),
            tuple(sorted(PINS.items())),
        )
        if _RUNTIME.tokenizer is not None:
            if identity != _RUNTIME.identity:
                raise ValueError(REASON_RESTART_REQUIRED)
            self._tokenizer = _RUNTIME.tokenizer
        else:
            self._tokenizer = _install_native(root, identity)

    @property
    def tokenizer(self) -> Tokenizer:
        """Return the validated native tokenizer shared process-wide."""
        return self._tokenizer

    def reservation(self, body: object) -> int:
        """Reserve the full budget for oversized bodies or count rendered tokens."""
        messages = contract(body)
        if not raw_fits(body):
            return FULL_BUDGET_RESERVATION
        request = cast("dict[str, object]", body)
        prompt = render(body)
        schema = json.dumps(request["response_format"], ensure_ascii=False).encode("utf-8")
        proxy_floor = (
            sum(len(message["content"]) for message in messages) + PROXY_EXTRA_CHARS
        ) // PROXY_CHARS_PER_TOKEN + PROXY_FLOOR_FRAMING
        with _ENCODE:
            count = len(self._tokenizer.encode(prompt, add_special_tokens=False).ids)
        return max(count + len(schema) + PROXY_FLOOR_FRAMING, proxy_floor) + cast(
            "int", request["max_tokens"]
        )


def configured_counter() -> LocalCounter | None:
    """Select the reviewed accounting mode from the environment."""
    mode = os.environ.get("SPI_TOKEN_ACCOUNTING_MODE", "byte-bound-v1")
    if mode == "byte-bound-v1":
        return None
    if mode == "local-qwen-v1":
        return LocalCounter()
    raise Failure(CODE_MODE_INVALID)
