"""Catalog-size regressions: mock HTTP/model, no production inference."""

import copy
import time
import unittest
from unittest.mock import Mock

import test_triage as f
from core import Failure
from integrations import GitHub, Model

GOOD = {
    "issue_number": 0,
    "reason": "No shared cause established.",
    "confidence": "low",
}


class LargeCatalogTests(unittest.TestCase):
    """Tests for dispatcher behaviour on large SPI catalogs."""

    @staticmethod
    def issues(n) -> list[dict[str, object]]:
        """Build n synthetic open issues."""
        return [
            {
                "number": i + 1,
                "title": "[SPI] fixture",
                "body": "bounded fixture",
                "updated_at": "2026-11-08T00:00:00Z",
            }
            for i in range(n)
        ]

    def test_121_open_issues_can_be_fingerprinted_without_model_review(self) -> None:
        """Verify 121 open issues are fingerprinted without model review."""
        g = GitHub(Mock(), "unused")
        fingerprinted_issues = 121
        rows = self.issues(fingerprinted_issues)
        g.pages = Mock(side_effect=lambda path: iter(copy.deepcopy(rows)))
        actual = g.issues()
        assert len(actual) == fingerprinted_issues
        assert g.open_signature() == f.digest([(x["number"], x["updated_at"]) for x in rows])
        g.http.request.assert_not_called()

    def test_all_241_issues_reviewed_with_unchanged_per_request_bounds(self) -> None:
        """Verify all 241 issues review with unchanged request bounds."""
        m = Model(Mock(), "test-only", store=Mock())
        seen = []

        def call(task, data, schema, deadline) -> "dict[str, object]":
            batch = data["open_issues"]
            # Match batches are capped: at most 12 issues, 30k reserved tokens, 30 min.
            batch_size_limit = 12
            reservation_limit = 30000
            deadline_window_seconds = 1800
            assert len(batch) <= batch_size_limit
            assert m.budget_reservation(m.payload(task, data, schema)) <= reservation_limit
            assert deadline - time.monotonic() <= deadline_window_seconds
            seen.extend(x["number"] for x in batch)
            return dict(GOOD)

        m.call = call
        result = m.match(f.event(), self.issues(241))
        assert seen == list(range(1, 242))
        assert result["reviewed_numbers"] == seen
        assert result["candidates"] == []
        m.http.request.assert_not_called()

    def test_admission_resume_reuses_existing_v3_paid_batch_receipts(self) -> None:
        """Verify admission resumes reuse existing paid batch receipts."""
        m = Model(Mock(), "test-only", store=Mock())
        rows = self.issues(121)
        saved = []
        calls = []
        # The third batch defers admission; the resumed receipt keeps version 3
        # with two reviewed batches.
        deferred_batch = 3
        receipt_version = 3
        reviewed_batches = 2

        def first(task, data, schema, deadline) -> "dict[str, object]":
            calls.append([x["number"] for x in data["open_issues"]])
            if len(calls) == deferred_batch:
                raise Failure("LLM_ADMISSION_DEFERRED", 61)
            return dict(GOOD)

        m.call = first
        with self.assertRaisesRegex(Failure, "LLM_ADMISSION_DEFERRED"):
            m.match(f.event(), rows, on_progress=lambda p: saved.append(copy.deepcopy(p)))
        assert saved[-1]["version"] == receipt_version
        assert len(saved[-1]["reviews"]) == reviewed_batches
        completed = [x for batch in calls[:2] for x in batch]
        resumed = []

        def second(task, data, schema, deadline) -> "dict[str, object]":
            resumed.extend(x["number"] for x in data["open_issues"])
            return dict(GOOD)

        m.call = second
        result = m.match(f.event(), rows, progress=saved[-1])
        assert result["reviewed_numbers"] == list(range(1, 122))
        assert not set(completed) & set(resumed)
        assert completed + resumed == list(range(1, 122))


if __name__ == "__main__":
    unittest.main()
