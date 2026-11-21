"""Offline contracts for in-process source-privacy redaction helpers."""

import importlib.util
import math
from pathlib import Path
from types import ModuleType
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "source_privacy", ROOT / "scripts/otel-sdk-source-privacy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SourcePrivacyTests(unittest.TestCase):
    """Private attributes and URL secrets are removed; numeric values stay."""

    def test_only_private_attributes_removed_and_numeric_values_preserved(self) -> None:
        """Drop private keys, keep numbers, and leave the input mapping intact."""
        module = load()
        before = {
            "authorization": "synthetic",
            "exception.message": "synthetic",
            "error.message": "synthetic",
            "gen_ai.input.messages": "synthetic",
            "latency": 0.0,
            "negative_zero": -0.0,
            "valid": False,
            "normal": "unchanged",
        }
        after = module.attributes(before)
        self.assertEqual(set(after), {"latency", "negative_zero", "valid", "normal"})
        self.assertEqual(after["normal"], "unchanged")
        self.assertFalse(after["valid"])
        self.assertEqual(math.copysign(1, after["negative_zero"]), -1)
        self.assertIn("authorization", before)

    def test_url_credentials_query_and_fragment_do_not_survive(self) -> None:
        """Remove URL userinfo, query, and fragment from redacted copies."""
        module = load()
        value = "https://synthetic-user:synthetic-password@example.test:443/path?api_key=synthetic-token#fragment"
        cleaned = module.safe_url(value)
        for private in ["synthetic-user", "synthetic-password", "synthetic-token", "fragment"]:
            self.assertNotIn(private, cleaned)
        self.assertIn("example.test:443/path", cleaned)
        self.assertEqual(
            module.attributes({"url.query": "secret-data"}), {"url.query": "<redacted>"}
        )
        self.assertEqual(module.safe_name("GET " + value), "GET " + cleaned)

    def test_invalid_url_fails_closed_without_forwarding_original(self) -> None:
        """Replace an unparsable URL with the closed redaction marker."""
        self.assertEqual(load().safe_url("https://[invalid?secret=value"), "<redacted-invalid-url>")
