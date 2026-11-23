"""Offline primitive coverage only: no claim of end-to-end workflow integration."""

import tempfile
import unittest

import pytest
import test_triage as fixtures
from core import Failure, Store
from durable_wait import WaitOwners


class WaitTests(unittest.TestCase):
    """Tests for durable wait persistence."""

    def setUp(self) -> None:
        """Create a scratch store and wait keys."""
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name + "/db", minute_token_limit=60000)
        self.key = self.store.enqueue(fixtures.event())["job_id"]
        self.store.claim()
        self.owners = WaitOwners(self.store)
        self.owner = self.owners.bind(self.key, "1234", "revision1", "match", 100)

    def tearDown(self) -> None:
        """Close the scratch store."""
        self.tmp.cleanup()

    def test_repeat_wait_restart_fence_and_deadline(self) -> None:
        """Verify repeat waits, restart fencing and deadlines."""
        owner = self.owner
        for now in (100, 200, 300):
            waiting = self.owners.defer(owner, "LLM_ADMISSION_DEFERRED", 61, now)
            assert waiting["due"] == now + 66
            assert self.owners.defer(owner, "LLM_ADMISSION_DEFERRED", 61, now + 1) == waiting
            restarted = WaitOwners(Store(self.store.path, minute_token_limit=60000))
            owner = restarted.resume(waiting, now + 66)
            with pytest.raises(Failure):
                restarted.resume(waiting, now + 66)
        assert owner["deadline"] == 21700
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM job_failure_budget").fetchone()[0] == 0
            assert c.execute("SELECT count(*) FROM llm_admission").fetchone()[0] == 0

    def test_strict_errors_and_owners(self) -> None:
        """Verify strict error handling for every owner and error code."""
        for code in ("LLM_INVALID_EVIDENCE_REFERENCE", "LLM_HTTP_401", "UNKNOWN"):
            with pytest.raises(Failure):
                self.owners.defer(self.owner, code, 61, 100)
        with pytest.raises(Failure):
            self.owners.bind(self.key, "5678", "revision1", "match", 100)
        waiting = self.owners.defer(self.owner, "LLM_ADMISSION_DEFERRED", 61, 100)
        for bad in (
            {**waiting, "revision": "revision2"},
            {**waiting, "stage": "analyze"},
            {**waiting, "fence": "bad"},
        ):
            with pytest.raises(Failure):
                self.owners.resume(bad, 166)
        with pytest.raises(Failure):
            self.owners.resume(waiting, 165)
        with pytest.raises(Failure):
            self.owners.resume(waiting, waiting["expires"])

    def test_opt_in_preserves_rpm_parallel_and_restart(self) -> None:
        """Verify opt-in keeps RPM, parallelism and restart semantics."""
        reservation = self.store.reserve_llm(1, now=100)
        restarted = Store(self.store.path, minute_token_limit=60000)
        with pytest.raises(Failure):
            restarted.reserve_llm(1, now=101)
        self.store.finish_llm(reservation, now=101)
        for now in (102, 103):
            reservation = restarted.reserve_llm(1, now=now)
            restarted.finish_llm(reservation, now=now)
        with pytest.raises(Failure):
            restarted.reserve_llm(1, now=104)
        restarted.reserve_llm(1, now=162)

    def test_idempotent_bind_and_invalid_wait_bounds(self) -> None:
        """Verify binding idempotence and rejected out-of-bound waits."""
        assert self.owner == self.owners.bind(self.key, "1234", "revision1", "match", 101)
        for value in (float("nan"), float("inf"), -1, True, "61"):
            with pytest.raises(Failure):
                self.owners.defer(self.owner, "LLM_ADMISSION_DEFERRED", value, 100)
        with self.store.db() as c:
            c.execute(
                "UPDATE workflow_wait_owner SET deadline=200 WHERE job_id=?",
                (self.key,),
            )
        with pytest.raises(Failure):
            self.owners.defer(self.owner, "LLM_ADMISSION_DEFERRED", 61, 100)

    def test_minute_budget_not_context_bound(self) -> None:
        """Verify waits budget by minute, not by context size."""
        for now in (100, 101):
            reservation = self.store.reserve_llm(30000, now=now)
            self.store.finish_llm(reservation, now=now)
        with pytest.raises(Failure) as error:
            self.store.reserve_llm(1, now=102)
        assert error.value.code == "LLM_ADMISSION_DEFERRED"
        with pytest.raises(Failure) as error:
            self.store.reserve_llm(30001, now=200)
        assert error.value.code == "LLM_REQUEST_TOO_LARGE"
        with pytest.raises(ValueError):
            Store(self.store.path, minute_token_limit=True)


if __name__ == "__main__":
    unittest.main()
