"""Tests for the blog updates stage helpers module."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/blog_updates"))
from stages import checked_model
from engine import UnsafeInput

# checked_model retries a rejected model answer once, so a bad answer is seen twice.
MODEL_CALL_CEILING = 2


class ModelBoundaryTests(unittest.TestCase):
    """Tests for blog update model boundaries and retries."""

    def test_retry_schema_failure(self) -> None:

        'Verify schema failures are retried without marking success.'
        calls = []
        valid = {
            "should_update": True,
            "reason": "Published",
            "entries": [{"text": "New poem.", "source_paths": ["a"]}],
        }

        def model(prompt, data) -> object:
            calls.append(prompt)
            return {"extra": True} if len(calls) == 1 else valid

        assert checked_model(model, "prompt", {}, {"files": [{"filename": "a"}]}) == valid
        assert len(calls) == MODEL_CALL_CEILING

    def test_bad_output_stays_rejected(self):
        'Verify malformed stage output stays rejected across retries.'
        calls = []

        def model(prompt, data) -> object:
            calls.append(1)
            return []

        with self.assertRaises(UnsafeInput):
            checked_model(model, "prompt", {}, {"files": []})
        assert len(calls) == MODEL_CALL_CEILING
