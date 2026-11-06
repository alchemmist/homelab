import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'charts/spi-triage/files'))
from core import Failure
from local_token_counter import configured_counter, render, LocalCounter


class CounterContract(unittest.TestCase):
    def body(self):
        return dict(model='qwen3.8-27b', messages=[dict(role='system', content=' s '), dict(role='user', content=' u ')], chat_template_kwargs={'enable_thinking': False}, max_tokens=768)

    def test_render(self):
        self.assertEqual(render(self.body()), '<|im_start|>system\ns<|im_end|>\n<|im_start|>user\nu<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n')

    def test_contract_and_size(self):
        for key, value in [('model', 'other'), ('tools', []), ('max_tokens', 1), ('chat_template_kwargs', {'enable_thinking': True})]:
            body = self.body(); body[key] = value
            with self.assertRaises(Failure): render(body)
        body = self.body(); body['messages'][1]['content'] = 'a' * 524289
        with self.assertRaises(Failure): render(body)

    def test_modes_and_missing_assets(self):
        with patch.dict(os.environ, {'SPI_TOKEN_ACCOUNTING_MODE': 'byte-bound-v1'}):
            self.assertIsNone(configured_counter())
        with patch.dict(os.environ, {'SPI_TOKEN_ACCOUNTING_MODE': 'unknown'}):
            with self.assertRaises(Failure): configured_counter()
        with self.assertRaises(Failure): LocalCounter('/nonexistent/spi-tokenizer')
