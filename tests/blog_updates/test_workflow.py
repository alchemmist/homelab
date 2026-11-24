"""Tests for the blog updates stage helpers module."""

import unittest

import pytest

from scripts.blog_updates import core as e
from scripts.blog_updates.core import UnsafeInputError
from scripts.blog_updates.workflow import checked_model

# checked_model retries a rejected model answer once, so a bad answer is seen twice.
MODEL_CALL_CEILING = 2


class ModelBoundaryTests(unittest.TestCase):
    """Tests for blog update model boundaries and retries."""

    def test_retry_schema_failure(self) -> None:
        """Verify schema failures are retried without marking success."""
        calls = []
        valid = {
            "should_update": True,
            "reason": "Published",
            "entries": [{"text": "New poem.", "source_paths": ["a"]}],
        }

        def model(prompt: str, data: object) -> object:
            calls.append(prompt)
            del data  # the stub only records prompts
            return {"extra": True} if len(calls) == 1 else valid

        context: e.Context = {
            "files": [{"filename": "a"}],
            "recent_updates": "",
            "commits": [],
        }
        assert checked_model(model, "prompt", {}, context) == valid
        assert len(calls) == MODEL_CALL_CEILING

    def test_bad_output_stays_rejected(self) -> None:
        """Verify malformed stage output stays rejected across retries."""
        calls = []

        def model(prompt: str, data: object) -> object:
            del prompt, data  # the stub always answers with a malformed payload
            calls.append(1)
            return []

        context: e.Context = {"files": [], "recent_updates": "", "commits": []}
        with pytest.raises(UnsafeInputError):
            checked_model(model, "prompt", {}, context)
        assert len(calls) == MODEL_CALL_CEILING
