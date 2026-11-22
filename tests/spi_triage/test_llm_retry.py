"""Busy LLM is durable pending work, not an exhausted job or repeated publication."""

import json
import time
import unittest
import urllib.error
from unittest.mock import Mock

import pytest
import test_triage as f
from core import LLM_TRANSIENT, MATCH_SCHEMA, Failure, Store
from integrations import HTTP, Model


class DurableRetryTests(unittest.TestCase):
    """Tests for durable LLM retry behavior."""

    setUp = f.CoreTests.setUp
    tearDown = f.CoreTests.tearDown

    def test_many_transient_failures_survive_restart_then_complete(self) -> None:
        """Verify many transient failures survive restart and complete."""
        e = f.event()
        key = self.store.enqueue(e)["job_id"]
        # The Retry-After hint is preserved verbatim across restarts.
        retry_hint_seconds = 7200
        expected_attempts = 21
        for _ in range(20):
            assert self.store.claim()["job_id"] == key
            self.store.fail(key, "LLM_HTTP_429", retry_after=retry_hint_seconds)
            r = self.store.get(key)
            assert r["state"] == "retry"
            assert r["lease"] == 0
            assert r["available"] - r["updated"] >= retry_hint_seconds
            assert self.store.claim()["job_id"] == ""
            self.store = Store(self.store.path)
            with self.store.db() as c:
                c.execute("update jobs set available=0 where id=?", (key,))
        self.store.claim()
        self.store.save(key, 4, {"done": True}, state="complete")
        assert self.store.get(key)["state"] == "complete"
        assert self.store.get(key)["attempts"] == expected_attempts

    def test_permanent_and_ambiguous_errors_still_stop(self) -> None:
        """Verify permanent and ambiguous errors still stop retrying."""
        for index, code in enumerate(
            [
                "HTTP_429",
                "LLM_HTTP_400",
                "LLM_HTTP_401",
                "LLM_HTTP_403",
                "WRITE_NEEDS_REVIEW",
            ]
        ):
            key = self.store.enqueue(f.event(start="2026-11-03T13:00:%02dZ" % index))["job_id"]
            with self.store.db() as c:
                c.execute("update jobs set attempts=50 where id=?", (key,))
            for i in range(8):
                self.store.fail(key, code)
                # Attempt indices are zero-based: the 8th attempt is the last.
                last_attempt = 7
                expected = "dead" if code == "WRITE_NEEDS_REVIEW" or i == last_attempt else "retry"
                assert self.store.get(key)["state"] == expected
            self.store = Store(self.store.path)
            with self.store.db() as c:
                failure_budget_spent = 8
                assert (
                    c.execute(
                        "select failures from job_failure_budget where job_id=?", (key,)
                    ).fetchone()[0]
                    == failure_budget_spent
                )

    def test_jitter_cap_and_retry_hint_validation(self) -> None:
        """Verify jitter caps and retry-hint validation."""
        key = self.store.enqueue(f.event())["job_id"]
        with self.store.db() as c:
            c.execute("update jobs set attempts=10000 where id=?", (key,))
        self.store.fail(key, "LLM_UPSTREAM_TIMEOUT")
        r = self.store.get(key)
        # Jittered backoff stays within the bounded 50-60 minute window.
        jittered_delay_floor = 3000
        jittered_delay_ceiling = 3600
        assert r["available"] - r["updated"] >= jittered_delay_floor
        assert r["available"] - r["updated"] <= jittered_delay_ceiling
        assert Failure("x", float("nan")).retry_after is None
        # Retry-After hints are capped at one day.
        retry_after_cap = 86400
        assert Failure("x", 999999).retry_after == retry_after_cap


class ModelRetryTests(unittest.TestCase):
    """Tests for model retry classification hints."""

    def test_transport_classification_and_hint_preserved(self) -> None:
        """Verify transport classification preserves retry hints."""
        for code in [
            "HTTP_429",
            "HTTP_503",
            "HTTP_504",
            "UPSTREAM_TIMEOUT",
            "UPSTREAM_NETWORK_ERROR",
        ]:
            http = Mock()
            hint_seconds = 91
            http.request.side_effect = Failure(code, retry_after=hint_seconds)
            with pytest.raises(Failure) as caught:
                Model(http, "fake", min_interval=0, store=Mock()).call(
                    "test", {}, MATCH_SCHEMA, time.monotonic() + 30
                )
            assert caught.value.code in LLM_TRANSIENT
            assert caught.value.retry_after == hint_seconds
            assert http.request.call_count == 1  # durable queue retry, no busy loop

    def test_retry_after_seconds_and_date(self) -> None:
        """Verify retry hints in seconds and HTTP-date forms."""
        from email.utils import formatdate

        for value in [
            "120",
            formatdate(time.time() + 180, usegmt=True),
            "invalid",
            "NaN",
        ]:
            h = HTTP()
            h.opener = Mock()
            h.opener.open.side_effect = urllib.error.HTTPError(
                "http://internal", 429, "busy", {"Retry-After": value}, None
            )
            with pytest.raises(Failure) as caught:
                h.request("GET", "http://internal")
            if value in ["invalid", "NaN"]:
                assert caught.value.retry_after is None
            else:
                # A Retry-After above two minutes survives parsing into the hint.
                minimum_hint_seconds = 100
                assert caught.value.retry_after > minimum_hint_seconds

    def test_batch_checkpoint_resumes_and_changed_snapshot_invalidates(self) -> None:
        """Verify batch checkpoints resume and invalidate on change."""
        good = {"issue_number": 0, "reason": "Different", "confidence": "low"}
        issues = [{"number": i} for i in range(25)]
        m = Model(Mock(), "fake")
        m.call = Mock(side_effect=[good, Failure("LLM_HTTP_503")])
        saved = []
        with pytest.raises(Failure):
            m.match(
                f.event(),
                issues,
                on_progress=lambda p: saved.append(json.loads(json.dumps(p))),
            )
        assert len(saved[-1]["reviews"]) == 1
        m.call = Mock(return_value=good)
        r = m.match(f.event(), issues, progress=saved[-1])
        remaining_batches = 2
        assert m.call.call_count == remaining_batches
        assert r["reviewed_numbers"] == list(range(25))
        m.call.reset_mock()
        m.match(f.event(), [*issues, {"number": 25}], progress=saved[-1])
        assert m.call.call_count == remaining_batches


class EngineCheckpointTests(unittest.TestCase):
    """Tests for engine retry checkpoints."""

    setUp = f.EngineTests.setUp
    tearDown = f.EngineTests.tearDown

    def test_partial_matching_checkpoint_saved_before_busy_failure(self) -> None:
        """Verify partial match checkpoints save before busy failures."""

        def matching(event, issues, progress=None, on_progress=None) -> None:
            on_progress({"signature": "test", "decisions": []})
            msg = "LLM_HTTP_429"
            raise Failure(msg)

        self.model.match.side_effect = matching
        key = self.store.enqueue(f.event())["job_id"]
        self.store.claim()
        with pytest.raises(Failure):
            self.engine.run("match", key)
        r = self.store.get(key)
        assert r["result"]["match_progress_v3"]["signature"] == "test"
        assert r["state"] == "retry"
        self.github.request.assert_not_called()

    def test_many_llm_deferrals_do_not_exhaust_github_reconciliation(self) -> None:
        """Verify many LLM deferrals cannot exhaust reconciliation."""
        key = self.store.enqueue(f.event())["job_id"]
        self.model.match.side_effect = Failure("LLM_HTTP_429")
        for _ in range(20):
            self.store.claim()
            with pytest.raises(Failure):
                self.engine.run("match", key)
            assert self.store.get(key)["state"] == "retry"
            with self.store.db() as c:
                c.execute("update jobs set available=0 where id=?", (key,))
        self.model.match.side_effect = None
        self.store.claim()
        for stage in ["match", "collect", "analyze"]:
            self.engine.run(stage, key)
        self.engine.write = True
        self.github.request.side_effect = Failure("UPSTREAM_TIMEOUT")
        with pytest.raises(Failure):
            self.engine.run("publish", key)
        r = self.store.get(key)
        assert r["state"] == "retry"
        assert r["intent"] is not None
        self.store = Store(self.store.path)
        self.engine.store = self.store
        with self.store.db() as c:
            assert (
                c.execute(
                    "select failures from job_failure_budget where job_id=?", (key,)
                ).fetchone()[0]
                == 1
            )
            c.execute("update jobs set available=0 where id=?", (key,))
        self.github.reconcile.return_value = 7
        self.store.claim()
        self.engine.run("publish", key)
        assert self.store.get(key)["state"] == "complete"
        self.github.request.assert_called_once()
