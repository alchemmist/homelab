"""Tests for the blog updates GitHub client module."""

import unittest
from typing import override, cast

import pytest

from scripts.blog_updates.client import GitHub
from scripts.blog_updates.core import UnsafeInputError


class Fake(GitHub):
    """In-memory GitHub stub recording API calls."""

    def __init__(self, existing: object = None, main: str | None = None) -> None:
        """Script the stub with canned PR listings and a main-SHA."""
        super().__init__("test-token")
        self.calls: list[tuple[str, str, object]] = []

        self.existing = existing or []
        self.main = main or "a" * 40

    @override
    def api(self, method: str, path: str, body: object = None) -> object:
        """Record a call and return the scripted next response (no network)."""
        self.calls.append((method, path, body))
        if path.startswith("pulls?"):
            return self.existing
        if path == "git/ref/heads/main":
            return {"object": {"sha": self.main}}
        if method == "POST" and path == "pulls":
            return {"html_url": "https://github.com/alchemmist/blog/pull/1"}
        return {}

    @override
    def read_updates(self, _ref: str) -> tuple[str, str]:
        """Return the scripted updates file for any ref."""
        del _ref  # one snapshot is scripted for every ref
        return "original", "file-sha"


class WriterTests(unittest.TestCase):
    """Tests for the blog update PR writer."""

    def test_closed_pr_not_reopened(self) -> None:
        """Verify an existing closed PR is reused, not reopened."""
        g = Fake(existing=[{"html_url": "closed-pr", "state": "closed"}])
        assert g.propose("a" * 40, "new", "why")["status"] == "existing"
        assert all(c[0] == "GET" for c in g.calls)

    def test_advanced_main_refused(self) -> None:
        """Verify staging work never targets the main branch."""
        g = Fake(main="b" * 40)
        with pytest.raises(UnsafeInputError):
            g.propose("a" * 40, "new", "why")
        assert all(c[0] == "GET" for c in g.calls)

    def test_only_updates_written(self) -> None:
        """Verify the flow only ever writes the updates file."""
        g = Fake()
        r = g.propose("a" * 40, "new", "why")
        assert r["status"] == "created"
        writes = [c for c in g.calls if c[0] == "PUT"]
        assert [c[1] for c in writes] == ["contents/site/content/updates.md"]
        assert (
            cast("dict[str, object]", writes[0][2])["branch"]
            == "automation/blog-updates-" + "a" * 40
        )
        assert not any("merge" in c[1] for c in g.calls)

    def test_no_change_no_branch(self) -> None:
        """Verify no branch or PR is created when nothing changed."""
        g = Fake()
        assert g.propose("a" * 40, "original", "why")["status"] == "no_change"
        assert all(c[0] == "GET" for c in g.calls)
