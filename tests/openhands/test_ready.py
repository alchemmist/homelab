"""Tests for PR readiness evaluation in the scripts/openhands-pr-ready module."""

import copy
import importlib.util
import unittest
from pathlib import Path
from typing import cast

spec = importlib.util.spec_from_file_location(
    "pr_ready", Path(__file__).resolve().parents[2] / "scripts/openhands-pr-ready.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ReadyContract(unittest.TestCase):
    """Tests for the OpenHands ready-state contract."""

    def setUp(self) -> None:
        """Build the canonical PR snapshot fixture."""
        self.sha = "a" * 40
        self.p = {
            "state": "OPEN",
            "url": "https://github.com/o/r/pull/1",
            "headRefOid": self.sha,
            "mergeable": "MERGEABLE",
            "isDraft": False,
            "commits": {
                "nodes": [{"commit": {"oid": self.sha}}],
                "pageInfo": {"hasPreviousPage": False},
            },
            "reviews": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [
                    {
                        "id": "review",
                        "author": {"login": "review-bot", "__typename": "Bot"},
                        "state": "APPROVED",
                        "body": "",
                        "commit": {"oid": self.sha},
                    }
                ],
            },
            "comments": {"nodes": [], "pageInfo": {"hasNextPage": False}},
            "reviewThreads": {"nodes": [], "pageInfo": {"hasNextPage": False}},
            "statusCheckRollup": {
                "contexts": {
                    "pageInfo": {"hasNextPage": False},
                    "nodes": [
                        {
                            "__typename": "CheckRun",
                            "name": "tests",
                            "status": "COMPLETED",
                            "conclusion": "SUCCESS",
                        }
                    ],
                }
            },
        }

    def result(self) -> dict[str, object]:
        """Assess the fixture PR with the canonical reviewer sets."""
        return cast("dict[str, object]", m.assess(self.p, {"review-bot"}, {"publisher"}))

    def remark(self) -> None:
        """Install a resolved-bot-remark thread into the fixture."""
        self.p["reviewThreads"]["nodes"] = [
            {
                "id": "thread",
                "isResolved": True,
                "comments": {
                    "pageInfo": {"hasNextPage": False},
                    "nodes": [
                        {
                            "id": "remark",
                            "author": {"login": "review-bot", "__typename": "Bot"},
                            "body": "Please fix this bug.",
                        }
                    ],
                },
            }
        ]

    def test_closed_merged_unknown_state_are_not_ready(self) -> None:
        """Verify closed, merged and unknown PR states are not ready."""
        for state in ("CLOSED", "MERGED", None):
            self.p["state"] = state
            assert not self.result()["ready_to_review"]

    def test_green_complete(self) -> None:
        """Verify a fully green PR is marked ready to review."""
        assert self.result()["ready_to_review"]

    def test_skipped_failed_and_pending_are_not_green(self) -> None:
        """Verify skipped, failed and pending checks are not green."""
        for conclusion in ("SKIPPED", "NEUTRAL", "FAILURE", None):
            self.p["statusCheckRollup"]["contexts"]["nodes"][0]["conclusion"] = conclusion
            assert not self.result()["ready_to_review"]

    def test_no_reviewers_is_not_ready(self) -> None:
        """Verify a PR without reviewers is never ready."""
        assert not m.assess(self.p, set(), {"publisher"})["ready_to_review"]

    def test_old_review_is_not_current(self) -> None:
        """Verify reviews must match the head commit to count."""
        self.p["reviews"]["nodes"][0]["commit"]["oid"] = "b" * 40
        assert not self.result()["ready_to_review"]

    def test_resolved_without_reply_is_not_enough(self) -> None:
        """Verify a resolved thread without a reply is not enough."""
        self.remark()
        assert not self.result()["ready_to_review"]

    def test_fix_requires_link_and_commit_membership(self) -> None:
        """Verify a fix remark must link a commit in the PR."""
        self.remark()
        reply = {
            "id": "reply",
            "author": {"login": "publisher", "__typename": "Bot"},
            "body": '<!-- rtr:{"comment":"remark","decision":"fixed","commit":"'
            + self.sha
            + '"} -->',
        }
        self.p["comments"]["nodes"] = [reply]
        assert not self.result()["ready_to_review"]
        reply["body"] += "\nFixed: https://github.com/o/r/commit/" + self.sha
        assert self.result()["ready_to_review"]
        self.p["commits"]["nodes"] = []
        assert not self.result()["ready_to_review"]

    def test_rejection_requires_reason_then_resolve(self) -> None:
        """Verify rejections state a reason before being resolved."""
        self.remark()
        self.p["comments"]["nodes"] = [
            {
                "id": "reply",
                "author": {"login": "publisher", "__typename": "Bot"},
                "body": '<!-- rtr:{"comment":"remark","decision":"irrelevant","reason":"The proposed behavior conflicts with the documented local-only API contract; test X covers it."} -->',
            }
        ]
        assert self.result()["ready_to_review"]
        self.p["reviewThreads"]["nodes"][0]["isResolved"] = False
        assert not self.result()["ready_to_review"]

    def test_untrusted_actor_cannot_supply_disposition(self) -> None:
        """Verify untrusted actors cannot resolve a remark."""
        self.test_rejection_requires_reason_then_resolve()
        self.p["reviewThreads"]["nodes"][0]["isResolved"] = True
        self.p["comments"]["nodes"][0]["author"]["login"] = "someone-else"
        assert not self.result()["ready_to_review"]

    def test_conflict_draft_missing_checks_pagination(self) -> None:
        """Verify conflicting remarks, drafts and pagination fail safely."""
        original = copy.deepcopy(self.p)
        for field, value in [
            ("mergeable", "CONFLICTING"),
            ("isDraft", True),
            ("statusCheckRollup", None),
        ]:
            self.p = copy.deepcopy(original)
            self.p[field] = value
            assert not self.result()["ready_to_review"]
        self.p = original
        self.p["reviewThreads"]["pageInfo"] = {"hasNextPage": True}
        assert not self.result()["ready_to_review"]


if __name__ == "__main__":
    unittest.main()
