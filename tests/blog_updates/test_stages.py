import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/blog_updates"))
from engine import UnsafeInput
from stages import checked_model


class ModelBoundaryTests(unittest.TestCase):
    def test_retry_schema_failure(self):
        calls = []
        valid = {
            "should_update": True,
            "reason": "Published",
            "entries": [{"text": "New poem.", "source_paths": ["a"]}],
        }

        def model(prompt, data):
            calls.append(prompt)
            return {"extra": True} if len(calls) == 1 else valid

        self.assertEqual(checked_model(model, "prompt", {}, {"files": [{"filename": "a"}]}), valid)
        self.assertEqual(len(calls), 2)

    def test_bad_output_stays_rejected(self):
        calls = []

        def model(prompt, data):
            calls.append(1)
            return []

        with self.assertRaises(UnsafeInput):
            checked_model(model, "prompt", {}, {"files": []})
        self.assertEqual(len(calls), 2)
