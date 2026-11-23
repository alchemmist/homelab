"""Tests for the wiki_openapi engine and stages flow."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/wiki_openapi"))
import pytest
from engine import UnsafeInput, page_ok, select_closable, spec_changed
from stages import stage

SHA = "a" * 40

# Fixture pull-request numbers used by the create-pr / close-older stage flow.
CREATED_PR_NUMBER = 9
OLDER_PR_NUMBER = 4
BEFORE = "b" * 40


class Bot:
    """Test helper."""

    def __init__(self, files) -> None:
        self._files = files
        self.calls = 0

    def files(self, before, after):
        self.calls += 1
        return self._files

    def text(self, sha, path):
        if path.endswith("openapi.yaml"):
            return 'openapi: 3.0.3\ninfo:\n  title: x\npaths:\n  /v1/messages:\n    post:\n      summary: Send\n      responses:\n        "200":\n          description: ok\ncomponents:\n  schemas: {}\n'
        return Path("/Users/antonmoss/code/socrat-bot/scripts/render_wiki.py").read_text()


class Lab:
    """Test helper."""

    def __init__(self) -> None:
        self.closed = []
        self.page = "old"

    def read_page(self, ref="main"):
        return self.page, "blob"

    def propose(self, after, markdown):
        self.written = markdown
        return {
            "status": "created",
            "number": 9,
            "url": "https://github.com/alchemmist/homelab/pull/9",
        }

    def automation_prs(self, keep):
        return [
            {
                "number": 4,
                "title": "docs: refresh Socrat Bot wiki page",
                "body": "<!-- wiki-openapi-refresh -->",
                "url": "u",
            }
        ]

    def close(self, number, survivor) -> None:
        self.closed.append((number, survivor))


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
        assert "POST /v1/messages" in rendered[0]["markdown"]
        page_ok(rendered[0]["markdown"])
        lab = Lab()
        created = stage("create-pr", rendered[0], homelab=lab, write=True)
        assert created[0]["number"] == CREATED_PR_NUMBER

        def decide(prompt, data):
            assert data["candidates"][0]["number"] == OLDER_PR_NUMBER
            return {"close": [OLDER_PR_NUMBER, CREATED_PR_NUMBER, 99]}

        done = stage("close-older", created[0], homelab=lab, call_model=decide, write=True)
        assert lab.closed == [(OLDER_PR_NUMBER, CREATED_PR_NUMBER)]
        assert done[0]["closed"] == [4]

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
        with pytest.raises(UnsafeInput):
            page_ok("hello")


if __name__ == "__main__":
    unittest.main()
