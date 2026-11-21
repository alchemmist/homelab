"""Tests for the blog updates GitHub client module."""

import sys
from pathlib import Path
from typing import cast
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/blog_updates"))
from github import GitHub
from engine import UnsafeInput


class Fake(GitHub):
    """In-memory GitHub stub recording API calls."""

    def __init__(self, existing=None, main=None) -> None:
        self.calls: list[tuple[str, str, object]] = []

        self.existing = existing or []
        self.main = main or "a" * 40

    def api(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.startswith("pulls?"):
            return self.existing
        if path == "git/ref/heads/main":
            return {"object": {"sha": self.main}}
        if method == "POST" and path == "pulls":
            return {"html_url": "https://github.com/alchemmist/blog/pull/1"}
        return {}

    def read_updates(self, _ref):
        return "original", "file-sha"


class WriterTests(unittest.TestCase):
    """Tests for the blog update PR writer."""

    def test_closed_pr_not_reopened(self) -> None:

        g = Fake(existing=[{"html_url": "closed-pr", "state": "closed"}])
        assert g.propose("a" * 40, "new", "why")["status"] == "existing"
        assert all(c[0] == "GET" for c in g.calls)

    def test_advanced_main_refused(self) -> None:
        g = Fake(main="b" * 40)
        with self.assertRaises(UnsafeInput):
            g.propose("a" * 40, "new", "why")
        assert all(c[0] == "GET" for c in g.calls)

    def test_only_updates_written(self) -> None:
        g = Fake()
        r = g.propose("a" * 40, "new", "why")
        assert r["status"] == "created"
        writes = [c for c in g.calls if c[0] == "PUT"]
        assert [c[1] for c in writes] == ["contents/site/content/updates.md"]
        assert cast("dict[str, object]", writes[0][2])["branch"] == "automation/blog-updates-" + "a" * 40
        assert not any("merge" in c[1] for c in g.calls)

    def test_no_change_no_branch(self) -> None:
        g = Fake()
        assert g.propose("a" * 40, "original", "why")["status"] == "no_change"
        assert all(c[0] == "GET" for c in g.calls)
