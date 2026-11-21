"""Tests for the blog update engine loaded by file path."""

import importlib.util
import unittest
from pathlib import Path

s = importlib.util.spec_from_file_location(
    "engine", Path(__file__).resolve().parents[2] / "scripts/blog_updates/engine.py"
)
e = importlib.util.module_from_spec(s)
s.loader.exec_module(e)


class EngineTests(unittest.TestCase):
    """Offline rejection and render contracts for the blog-update engine."""

    def test_self_update_skipped(self) -> None:
        """Skip a compare that only touches the updates document."""
        assert e.prepare({"files": [{"filename": e.UPDATES}]}, "") is None

    def test_missing_diff_fails(self) -> None:
        """Reject a text change that arrives without a diff."""
        with self.assertRaises(e.UnsafeInput):
            e.prepare({"files": [{"filename": "site/layouts/index.html", "changes": 5}]}, "")

    def test_large_file_list_fails(self) -> None:
        """Reject a file list above the fail-closed limit."""
        with self.assertRaises(e.UnsafeInput):
            e.prepare({"files": [{"filename": "a"}] * 201}, "")

    def test_injection_rejected(self) -> None:
        """Reject links, markup, and line breaks in model text."""
        for text in ["[click](https://evil.test)", "<script>", "line\nline"]:
            with self.assertRaises(e.UnsafeInput):
                e.validate_decision(
                    {
                        "should_update": True,
                        "reason": "x",
                        "entries": [{"text": text, "source_paths": ["a"]}],
                    },
                    {"files": [{"filename": "a"}]},
                )

    def test_unsubstantiated_rejected(self) -> None:
        """Reject an entry whose source path is not in the compare."""
        with self.assertRaises(e.UnsafeInput):
            e.validate_decision(
                {
                    "should_update": True,
                    "reason": "x",
                    "entries": [{"text": "News", "source_paths": ["other"]}],
                },
                {"files": [{"filename": "a"}]},
            )

    def test_render_and_dedup(self) -> None:
        """Render a new entry once and keep the existing list item."""
        source = "---\ntitle: Updates\n---\n- [x] old\n"
        entries = [{"text": "New poem."}]
        result = e.render(source, entries, "2026-10-30T10:00:00Z")
        assert "2026-10-30 13:00" in result
        assert result == e.render(result, entries, "2026-10-30T11:00:00Z")
        assert result.endswith("- [x] old\n")

    def test_bad_event(self) -> None:
        """Reject an event that does not match the expected schema."""
        with self.assertRaises(e.UnsafeInput):
            e.validate_event({})


if __name__ == "__main__":
    unittest.main()
