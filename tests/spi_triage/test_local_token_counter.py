import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol, TypedDict
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "charts/spi-triage/files"))
from core import Failure
from local_token_counter import LocalCounter, configured_counter, render


class RequestMessage(TypedDict):
    """Minimal chat message payload used by the render fixture."""

    role: str
    content: str


class RequestBody(TypedDict, total=False):
    """Request payload accepted by the local counter contract."""

    model: str
    messages: list[RequestMessage]
    chat_template_kwargs: dict[str, object]
    max_tokens: int
    response_format: dict[str, object]


class CounterContract(unittest.TestCase):
    def body(self) -> RequestBody:
        result: RequestBody = {
            "model": "qwen3.8-27b",
            "messages": [
                {"role": "system", "content": " s "},
                {"role": "user", "content": " u "},
            ],
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": 768,
        }
        return result

    def test_render(self) -> None:
        self.assertEqual(
            render(self.body()),
            "<|im_start|>system\ns<|im_end|>\n<|im_start|>user\nu<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n",
        )

    def test_contract_and_size(self) -> None:
        for key, value in [
            ("model", "other"),
            ("tools", []),
            ("max_tokens", 1),
            ("chat_template_kwargs", {"enable_thinking": True}),
        ]:
            body = self.body()
            invalid: dict[str, object] = dict(body)
            invalid[key] = value
            with self.assertRaises(Failure):
                render(invalid)
        body = self.body()
        body["messages"][1]["content"] = "a" * 524289
        with self.assertRaises(Failure):
            render(body)

    def test_modes_and_missing_assets(self) -> None:
        with patch.dict(os.environ, {"SPI_TOKEN_ACCOUNTING_MODE": "byte-bound-v1"}):
            self.assertIsNone(configured_counter())
        with patch.dict(os.environ, {"SPI_TOKEN_ACCOUNTING_MODE": "unknown"}):
            with self.assertRaises(Failure):
                configured_counter()
        with self.assertRaises(Failure):
            LocalCounter("/nonexistent/spi-tokenizer")


class ProxyCounter(Protocol):
    """Duck-type of a LocalCounter built without touching its tokenizer assets."""

    _tokenizer: SimpleNamespace | Mock

    def reservation(self, body: object) -> int:
        """Return the reserved token budget for a request body."""
        ...


class ProxyFloor(unittest.TestCase):
    def counter(self) -> ProxyCounter:
        from types import SimpleNamespace

        counter: ProxyCounter = object.__new__(LocalCounter)
        counter._tokenizer = SimpleNamespace(encode=lambda *a, **kw: SimpleNamespace(ids=[1] * 10))
        return counter

    def body(self, text: str, maximum: int = 2500) -> RequestBody:
        result: RequestBody = {
            "model": "qwen3.8-27b",
            "messages": [
                {"role": "system", "content": "s"},
                {"role": "user", "content": text},
            ],
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": maximum,
            "response_format": {},
        }
        return result

    def test_raw_floor_and_rounding(self) -> None:
        for text in [" " * 100000 + "x", "a" * 60000, '😀\\"\n' * 1000] + [
            "x" * n for n in range(8)
        ]:
            for maximum in (768, 2500):
                body = self.body(text, maximum)
                actual = self.counter().reservation(body)
                self.assertGreaterEqual(actual, (len(text) + 1 + 3) // 4 + maximum)
                self.assertGreaterEqual(actual, 10 + 2 + 256 + maximum)
                self.assertEqual(actual, max(268, (len(text) + 4) // 4 + 256) + maximum)

    def test_oversize_no_bpe_and_contract_not_masked(self) -> None:
        from unittest.mock import Mock

        counter = self.counter()
        counter._tokenizer = Mock()
        body = self.body(" " * 600000)
        self.assertEqual(counter.reservation(body), 30001)
        counter._tokenizer.encode.assert_not_called()
        for key, value in [
            ("metadata", {}),
            ("tools", []),
            ("model", "bad"),
            ("chat_template_kwargs", {"enable_thinking": True}),
        ]:
            bad = dict(body)
            bad[key] = value
            with self.assertRaises(Failure):
                counter.reservation(bad)
