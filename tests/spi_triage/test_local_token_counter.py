"""Tests for the local token counter used by SPI triage."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "charts/spi-triage/files"))
from core import Failure
from local_token_counter import LocalCounter, configured_counter, render


class CounterContract(unittest.TestCase):
    """Tests for the local token counter contract."""

    def body(self) -> dict[str, object]:
        """Return the canonical request body fixture."""
        return {
            "model": "qwen3.8-27b",
            "messages": [{"role": "system", "content": " s "}, {"role": "user", "content": " u "}],
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": 768,
        }

    def test_render(self) -> None:
        """Verify the rendered prompt matches the golden output."""
        assert (
            render(self.body())
            == "<|im_start|>system\ns<|im_end|>\n<|im_start|>user\nu<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )

    def test_contract_and_size(self) -> None:
        """Verify every contract key and size bound."""
        for key, value in [
            ("model", "other"),
            ("tools", []),
            ("max_tokens", 1),
            ("chat_template_kwargs", {"enable_thinking": True}),
        ]:
            body = self.body()
            body[key] = value
            with self.assertRaises(Failure):
                render(body)
        body = self.body()
        body["messages"][1]["content"] = "a" * 524289
        with self.assertRaises(Failure):
            render(body)

    def test_modes_and_missing_assets(self) -> None:
        """Verify accounting modes handle missing assets safely."""
        with patch.dict(os.environ, {"SPI_TOKEN_ACCOUNTING_MODE": "byte-bound-v1"}):
            assert configured_counter() is None
        with patch.dict(os.environ, {"SPI_TOKEN_ACCOUNTING_MODE": "unknown"}):
            with self.assertRaises(Failure):
                configured_counter()
        with self.assertRaises(Failure):
            LocalCounter("/nonexistent/spi-tokenizer")


class ProxyFloor(unittest.TestCase):
    """Tests for the proxy token-count floor."""

    def counter(self) -> LocalCounter:
        """Build a local counter instance."""
        from types import SimpleNamespace

        counter = object.__new__(LocalCounter)
        counter._tokenizer = SimpleNamespace(encode=lambda *a, **kw: SimpleNamespace(ids=[1] * 10))
        return counter

    def body(self, text, maximum=2500) -> dict[str, object]:
        """Return a request body with the given text and cap."""
        return {
            "model": "qwen3.8-27b",
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": text}],
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": maximum,
            "response_format": {},
        }

    def test_raw_floor_and_rounding(self) -> None:
        """Verify the raw floor and rounding rules."""
        for text in [" " * 100000 + "x", "a" * 60000, '😀\\"\n' * 1000] + [
            "x" * n for n in range(8)
        ]:
            for maximum in (768, 2500):
                body = self.body(text, maximum)
                actual = self.counter().reservation(body)
                assert actual >= (len(text) + 1 + 3) // 4 + maximum
                assert actual >= 10 + 2 + 256 + maximum
                assert actual == max(268, (len(text) + 4) // 4 + 256) + maximum

    def test_oversize_no_bpe_and_contract_not_masked(self) -> None:
        """Verify oversized inputs skip BPE and surface contract errors."""
        from unittest.mock import Mock

        counter = self.counter()
        counter._tokenizer = Mock()
        body = self.body(" " * 600000)
        # An oversize body claims the whole 30k-token budget plus one.
        full_reservation = 30001
        assert counter.reservation(body) == full_reservation
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
