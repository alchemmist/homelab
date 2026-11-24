"""Tests for the wiki_openapi engine and workflow stage flow."""

import unittest
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from scripts.wiki_openapi.engine import (
    UnsafeInputError,
    page_ok,
    select_closable,
    spec_changed,
)
from scripts.wiki_openapi.workflow import stage

SHA = "a" * 40

# Fixture pull-request numbers used by the create-pr / close-older stage flow.
CREATED_PR_NUMBER = 9
OLDER_PR_NUMBER = 4
BEFORE = "b" * 40
# A PR number the model invents; the stage must drop it.
UNLISTED_PR_NUMBER = 99

OPENAPI_FIXTURE = (
    "openapi: 3.0.3\ninfo:\n  title: x\npaths:\n  /v1/messages:\n    post:\n"
    '      summary: Send\n      responses:\n        "200":\n'
    "          description: ok\ncomponents:\n  schemas: {}\n"
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _render_wiki_source() -> str:
    """Return the renderer fixture run inside the render-stage sandbox."""
    return (FIXTURES / "render_wiki.py").read_text()


class Bot:
    """In-memory stand-in for the public bot repository."""

    def __init__(self, files: Iterable[object]) -> None:
        """Script the compare/commit file list this stub reports."""
        self._files = files
        self.calls = 0

    def files(self, before: object, after: object) -> Iterable[object] | None:
        """Count the read and return the scripted file list."""
        del before, after  # the stub ignores the SHA pair
        self.calls += 1
        return self._files

    def text(self, sha: object, path: str) -> str:
        """Return the fixture OpenAPI spec or renderer source."""
        del sha  # one commit is scripted, the SHA is not inspected
        if path.endswith("openapi.yaml"):
            return OPENAPI_FIXTURE
        return _render_wiki_source()


class Lab:
    """In-memory stand-in for the homelab wiki repository."""

    def __init__(self) -> None:
        """Start with an empty close log and a stale wiki page."""
        self.closed: list[tuple[int, object]] = []
        self.calls: list[tuple[str, str, object]] = []
        self.page = "old"

    def read_page(self, ref: str = "main") -> tuple[str, str]:
        """Return the scripted page and blob SHA."""
        del ref  # one page revision is scripted
        return self.page, "blob"

    def propose(self, after: object, markdown: str) -> Mapping[str, object]:
        """Record the proposal and report the created pull request."""
        del after  # the stage already verified the SHA before calling
        self.written = markdown
        return {
            "status": "created",
            "number": CREATED_PR_NUMBER,
            "url": f"https://github.com/alchemmist/homelab/pull/{CREATED_PR_NUMBER}",
        }

    def automation_prs(self, keep: object) -> list[Mapping[str, object]]:
        """Return one older automation PR regardless of the survivor."""
        del keep  # the survivor filtering is exercised through close()
        return [
            {
                "number": OLDER_PR_NUMBER,
                "title": "docs: refresh Socrat Bot wiki page",
                "body": "<!-- wiki-openapi-refresh -->",
                "url": "u",
            }
        ]

    def close(self, number: int, survivor: object) -> None:
        """Log the close call."""
        self.closed.append((number, survivor))

    def api(
        self,
        method: str,
        path: str,
        body: object = Ellipsis,
        *,
        token: str | None = None,
    ) -> object:
        """Log API writes the same way close() logs its calls."""
        del token  # the broker token is not asserted here
        self.calls.append((method, path, body))
        return {}


class Flow(unittest.TestCase):
    """Tests or helper for Flow."""

    def test_ignores_other_branches_without_github(self) -> None:
        bot = Bot([{"filename": "openapi.yaml"}])
        assert (
            stage(
                "check",
                {"ref": "refs/heads/dev", "before": BEFORE, "after": SHA},
                bot=bot,
            )
            == []
        )
        assert bot.calls == 0

    def test_ignores_push_that_does_not_touch_the_spec(self) -> None:
        event = {"ref": "refs/heads/main", "before": BEFORE, "after": SHA}
        assert not spec_changed(event, [{"filename": "README.md"}])
        assert stage("check", event, bot=Bot([{"filename": "README.md"}])) == []

    def test_render_and_pr_and_close(self) -> None:
        event = {"ref": "refs/heads/main", "before": BEFORE, "after": SHA}
        checked = stage("check", event, bot=Bot([{"filename": "openapi.yaml"}]))
        rendered = stage("render", checked[0], bot=Bot([]))
        markdown_value = rendered[0]["markdown"]
        assert isinstance(markdown_value, str)
        page_ok(markdown_value)
        assert "POST /v1/messages" in markdown_value
        lab = Lab()
        created = stage("create-pr", rendered[0], homelab=lab, write=True)
        assert created[0]["number"] == CREATED_PR_NUMBER

        def decide(prompt: str, data: object) -> object:
            del prompt  # the prompt content is not asserted here
            assert isinstance(data, dict)
            candidates = data["candidates"]
            assert isinstance(candidates, list)
            first = candidates[0]
            assert isinstance(first, dict)
            assert first["number"] == OLDER_PR_NUMBER
            return {"close": [OLDER_PR_NUMBER, CREATED_PR_NUMBER, UNLISTED_PR_NUMBER]}

        done = stage(
            "close-older", created[0], homelab=lab, call_model=decide, write=True
        )
        assert lab.closed == [(OLDER_PR_NUMBER, CREATED_PR_NUMBER)]
        assert done[0]["closed"] == [OLDER_PR_NUMBER]

    def test_model_cannot_close_unlisted_prs(self) -> None:
        assert select_closable({"close": [3, "4"]}, [{"number": 3}], None) == [3]

    def test_dry_run_does_not_close(self) -> None:
        lab = Lab()
        assert (
            stage(
                "close-older",
                {"status": "dry_run", "after": SHA},
                homelab=lab,
                write=False,
            )
            == []
        )
        assert lab.closed == []

    def test_bad_page_rejected(self) -> None:
        with pytest.raises(UnsafeInputError):
            page_ok("hello")


if __name__ == "__main__":
    unittest.main()
