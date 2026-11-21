"""Integrated worker/Store protocol tests, fake clock + fake model only."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import test_triage as f
from core import Store, Failure, MATCH_SCHEMA
from integrations import Model, REQUEST_DEADLINE
from service import Engine


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.clock = patch("time.time", lambda: self.now)
        self.clock.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name + "/db", minute_token_limit=60000)
        self.github = Mock()
        self.github.snapshot.return_value = []
        self.github.open_signature.return_value = f.digest([])
        self.github.request.return_value = {"number": 7}
        self.model = Mock()
        self.model.match.return_value = {"candidates": []}
        self.model.analyze.return_value = f.report()
        self.evidence = Mock()
        self.evidence.collect.return_value = {"missing": ["logs"]}
        self.engine = Engine(self.store, self.github, self.model, self.evidence, write=True)
        self.key = self.store.enqueue(f.event())["job_id"]
        self.identity = {"execution_id": "1234", "workflow_revision": "durable-v1"}
        self.data = self.engine.claim(self.identity)

    def tearDown(self):
        self.clock.stop()
        self.tmp.cleanup()

    def test_consecutive_deferrals_same_execution_then_published(self):
        self.model.match.side_effect = [
            Failure("LLM_ADMISSION_DEFERRED", 61),
            Failure("LLM_ADMISSION_DEFERRED", 180),
            {"candidates": []},
        ]
        original = self.data
        for _ in range(2):
            sent = self.data
            self.data = self.engine.run_v1("match", sent)
            assert self.data["status"] == "deferred"
            assert self.data["execution_id"] == "1234"
            assert self.store.get(self.key)["stage"] == 0
            self.evidence.collect.assert_not_called()
            assert not self.engine.lock.locked()
            calls = self.model.match.call_count
            assert self.engine.run_v1("match", sent) == self.data
            assert self.model.match.call_count == calls
            assert self.store.claim() == {"job_id": ""}
            self.store = Store(self.store.path, minute_token_limit=60000)
            self.store.recover_on_start()
            self.engine.store = self.store
            self.now = self.data["due_at"]
        self.data = self.engine.run_v1("match", self.data)
        for stage in ("collect", "analyze", "publish"):
            assert self.data["stage"] == stage
            self.data = self.engine.run_v1(stage, self.data)
            if stage != "publish":
                assert self.data["status"] != "complete"
        assert self.data["status"] == "complete"
        assert self.data["outcome"] == "complete"
        assert self.github.request.call_count == 1
        assert self.store.get(self.key)["attempts"] == 1
        with self.store.db() as c:
            assert c.execute("select count(*) from job_failure_budget").fetchone()[0] == 0
        with self.assertRaises(Failure):
            self.engine.run_v1("match", original)

    def test_finite_reference_error_retained_no_rewait(self):
        self.data = self.engine.run_v1("match", self.data)
        self.data = self.engine.run_v1("collect", self.data)
        self.model.analyze.side_effect = Failure("LLM_INVALID_EVIDENCE_REFERENCE")
        with self.assertRaisesRegex(Failure, "LLM_INVALID_EVIDENCE_REFERENCE"):
            self.engine.run_v1("analyze", self.data)
        job = self.store.get(self.key)
        assert job["state"] == "retry"
        # The failed analyze pass restarts from the collect stage.
        collect_stage = 2
        assert job["stage"] == collect_stage
        with self.store.db() as c:
            assert c.execute("select failures from job_failure_budget").fetchone()[0] == 1
        with self.assertRaises(Failure):
            self.engine.claim(self.identity)
        self.github.request.assert_not_called()

    def test_early_wrong_stale_resume_and_legacy_cannot_bypass(self):
        self.model.match.side_effect = Failure("LLM_ADMISSION_DEFERRED", 61)
        waiting = self.engine.run_v1("match", self.data)
        for bad in (
            {**waiting, "fence": "0" * 64},
            {**waiting, "workflow_revision": "wrong"},
            waiting,
        ):
            with self.assertRaises(Failure):
                self.engine.run_v1("match", bad)
        with self.assertRaises(Failure):
            self.engine.run("match", self.key)
        assert self.model.match.call_count == 1
        assert self.engine.claim(self.identity)["fence"] == waiting["fence"]
        for bad in ("0", "-1", "１２", "01", True, "9" * 33):
            with self.assertRaises(Failure):
                self.engine.claim({**self.identity, "execution_id": bad})

    def test_cancelled_wait_expiry_reclaims_progress_fences_old_execution(self):
        self.data = self.engine.run_v1("match", self.data)
        self.data = self.engine.run_v1("collect", self.data)
        self.model.analyze.side_effect = Failure("LLM_ADMISSION_DEFERRED", 61)
        waiting = self.engine.run_v1("analyze", self.data)
        self.now = waiting["due_at"] + 180
        fresh = self.engine.claim({**self.identity, "execution_id": "1235"})
        assert fresh["job_id"] == self.key
        assert fresh["stage"] == "analyze"
        with self.assertRaises(Failure):
            self.engine.run_v1("analyze", waiting)
        with self.assertRaises(Failure):
            self.engine.claim(self.identity)
        assert "evidence" in self.store.get(self.key)["result"]

    def test_owned_completion_priority_analysis_due_and_publish_ready(self):
        a = self.engine.run_v1("match", self.data)
        a = self.engine.run_v1("collect", a)
        # A pre-upgrade cohort can contain multiple owners. Seed B explicitly;
        # new admissions must no longer create that backlog during A's Wait.
        self.engine.lock.acquire()
        try:
            a = self.engine.run_v1("analyze", a)
        finally:
            self.engine.lock.release()
        key = self.store.enqueue(f.event(start="2026-11-03T14:00:00Z"))["job_id"]
        with self.store.db() as c:
            c.execute(
                "UPDATE jobs SET state='processing',lease=0,updated=? WHERE id=?", (self.now, key)
            )
        self.store.owners.bind(key, "4000", "durable-v1", "match", self.now)
        with self.store.db() as c:
            c.execute(
                "UPDATE workflow_wait_owner SET phase='ready',expires=? WHERE job_id=?",
                (self.now + 180, key),
            )
            b = self.store.owners.envelope(
                c.execute("SELECT * FROM workflow_wait_owner WHERE job_id=?", (key,)).fetchone()
            )
        assert b["stage"] == "match"
        self.now = a["due_at"]
        self.model.analyze.side_effect = Failure("LLM_ADMISSION_DEFERRED", 61)
        a = self.engine.run_v1("analyze", a)
        # Protect the short known analysis slot even before its due time.
        b = self.engine.run_v1("match", b)
        assert b["status"] == "deferred"
        assert self.model.match.call_count == 1
        self.now = max(a["due_at"], b["due_at"])
        old = b
        b = self.engine.run_v1("match", b)  # Low stage arrives before analysis wake.
        assert b["code"] == "WORKER_ADMISSION_DEFERRED"
        assert self.engine.run_v1("match", old) == b
        assert self.model.match.call_count == 1
        self.model.analyze.side_effect = None
        a = self.engine.run_v1("analyze", a)
        assert a["stage"] == "publish"
        self.now = b["due_at"]
        b = self.engine.run_v1("match", b)
        assert b["status"] == "deferred"  # Ready publish also wins.
        assert self.model.match.call_count == 1
        a = self.engine.run_v1("publish", a)
        assert a["status"] == "complete"
        self.now = b["due_at"]
        b = self.engine.run_v1("match", b)
        assert b["stage"] == "collect"
        # The second match runs against the refreshed wait payload.
        match_attempts = 2
        assert self.model.match.call_count == match_attempts

    def test_priority_hold_is_bounded_and_rejects_invalid_higher_owner(self):
        a = self.engine.run_v1("match", self.data)
        a = self.engine.run_v1("collect", a)
        self.model.analyze.side_effect = Failure("LLM_ADMISSION_DEFERRED", 180)
        a = self.engine.run_v1("analyze", a)
        with self.store.db() as c:
            assert (
                self.store._owned_priority_until(c, 0, self.now) == 0
            )  # Far future is not a reservation.
            assert self.store._owned_priority_until(c, 0, a["due_at"]) > a["due_at"]
            c.execute(
                "update workflow_wait_owner set revision='foreign' where job_id=?", (self.key,)
            )
            assert self.store._owned_priority_until(c, 0, a["due_at"]) == 0
            c.execute(
                "update workflow_wait_owner set revision='durable-v1' where job_id=?", (self.key,)
            )
            c.execute("update jobs set stage=1 where id=?", (self.key,))
            assert self.store._owned_priority_until(c, 0, a["due_at"]) == 0
            c.execute("update jobs set stage=2 where id=?", (self.key,))
            expiry = a["due_at"] + 180
            self.store._reconcile_owners(c, expiry)
            assert self.store._owned_priority_until(c, 0, expiry) == 0
        assert self.store.get(self.key)["state"] == "retry"

    def test_fresh_queued_match_waits_for_short_owned_analysis_slot(self):
        a = self.engine.run_v1("match", self.data)
        a = self.engine.run_v1("collect", a)
        self.model.analyze.side_effect = Failure("LLM_ADMISSION_DEFERRED", 61)
        a = self.engine.run_v1("analyze", a)
        key = self.store.enqueue(f.event(start="2026-11-03T14:00:00Z"))["job_id"]
        empty = self.engine.claim({**self.identity, "execution_id": "4000"})
        assert empty["status"] == "empty"
        assert self.store.get(key)["state"] == "queued"
        token, deadline = self.store.reserve_dispatch(self.now)
        assert token is None
        assert deadline == a["due_at"] + 180
        self.now = a["due_at"] + 180
        next_job = self.engine.claim({**self.identity, "execution_id": "4001"})
        assert next_job["job_id"] == self.key
        assert next_job["stage"] == "analyze"

    def test_fresh_v1_claim_acks_dispatch_replay_does_not_erase_new_wake(self):
        data = self.data
        for stage in ("match", "collect", "analyze", "publish"):
            data = self.engine.run_v1(stage, data)
        assert data["status"] == "complete"
        saved = None
        for i in range(8):
            self.store.enqueue(f.event(start="2026-11-03T14:%02d:00Z" % i))
            token, _ = self.store.reserve_dispatch(self.now)
            assert token is not None
            assert self.store.dispatch_status()["attempts"] == 1
            identity = {**self.identity, "execution_id": str(2000 + i)}
            data = self.engine.claim(identity)
            assert self.store.dispatch_status()["attempts"] == 0
            for stage in ("match", "collect", "analyze", "publish"):
                data = self.engine.run_v1(stage, data)
            assert data["status"] == "complete"
            saved = identity
        self.store.enqueue(f.event(start="2026-11-03T15:00:00Z"))
        token, _ = self.store.reserve_dispatch(self.now)
        assert token is not None
        self.engine.claim(saved)  # Duplicate old workflow must not ACK this wake.
        assert self.store.dispatch_status()["attempts"] == 1
        data = self.engine.claim({**self.identity, "execution_id": "3000"})
        assert self.store.dispatch_status()["attempts"] == 0
        # A fresh empty callback also acknowledges once; its replay never does.
        with self.store.db() as c:
            c.execute("INSERT INTO dispatch VALUES(1,'fixture',?,4)", (self.now + 30,))
        empty_id = {**self.identity, "execution_id": "3001"}
        assert self.engine.claim(empty_id)["status"] == "empty"
        assert self.store.dispatch_status()["attempts"] == 0
        with self.store.db() as c:
            c.execute("INSERT INTO dispatch VALUES(1,'fixture2',?,1)", (self.now + 30,))
        assert self.engine.claim(empty_id)["status"] == "empty"
        assert self.store.dispatch_status()["attempts"] == 1

    def test_busy_worker_30min_renews_wait_without_http_queue(self):
        wait_window_seconds = 1800
        reservation = self.store.reserve_llm(1, timeout=wait_window_seconds, now=self.now)
        self.engine.lock.acquire()
        try:
            start = self.now
            while self.now - start < wait_window_seconds:
                old = self.data
                self.data = self.engine.run_v1("match", old)
                assert self.data["code"] == "WORKER_ADMISSION_DEFERRED"
                assert self.engine.run_v1("match", old) == self.data
                self.store = Store(self.store.path, minute_token_limit=60000)
                self.store.recover_on_start()
                self.engine.store = self.store
                self.now = self.data["due_at"]
            self.model.match.assert_not_called()
            with self.store.db() as c:
                assert c.execute("select count(*) from llm_admission").fetchone()[0] == 1
                assert c.execute("select count(*) from job_failure_budget").fetchone()[0] == 0
            assert self.data["deadline"] == start + 21600
        finally:
            self.engine.lock.release()
        self.store.finish_llm(reservation, now=self.now)
        result = self.engine.run_v1("match", self.data)
        assert result["stage"] == "collect"

    def test_concurrent_same_claim_and_duplicate_stage_do_not_double_pay(self):
        import concurrent.futures, threading

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(
                pool.map(
                    lambda _: self.store.owners.claim("1234", "durable-v1", self.now), range(2)
                )
            )
        assert results[0] == results[1]
        entered = threading.Event()
        release = threading.Event()

        def model(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            return {"candidates": []}

        self.model.match.side_effect = model
        other_engine = Engine(Store(self.store.path), self.github, self.model, self.evidence)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            future = pool.submit(self.engine.run_v1, "match", self.data)
            assert entered.wait(3)
            try:
                with self.assertRaises(Failure):
                    other_engine.run_v1("match", self.data)
            finally:
                release.set()
            result = future.result(timeout=3)
        assert self.model.match.call_count == 1
        assert self.engine.run_v1("match", self.data) == result

    def test_running_crash_no_blind_model_replay(self):
        _, owner = self.store.owners.begin("match", self.data, self.now)
        restored = Store(self.store.path)
        assert restored.recover_on_start() == 0
        self.now += 1980
        assert restored.claim() == {"job_id": ""}
        assert restored.get(self.key)["state"] == "dead"
        assert restored.get(self.key)["error"] == "WRITE_NEEDS_REVIEW"

    def test_wait_releases_http_lock_but_retains_logical_owner(self):
        self.model.match.side_effect = Failure("LLM_ADMISSION_DEFERRED", 61)
        self.engine.run_v1("match", self.data)
        other = self.store.enqueue(f.event(start="2026-11-03T14:00:00Z"))["job_id"]
        claimed = self.engine.claim({**self.identity, "execution_id": "1235"})
        assert claimed["status"] == "empty"
        assert not self.engine.lock.locked()
        assert self.store.get(other)["state"] == "queued"
        assert self.store.get(other)["attempts"] == 0


class ModelTimerTests(unittest.TestCase):
    @patch.dict("os.environ", {"SPI_TOKEN_ACCOUNTING_MODE": "byte-bound-v1"})
    def test_active_reservation_survives_old_661_second_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp + "/db", minute_token_limit=60000)
            http = Mock()
            model = Model(http, "fake", store=store)
            now = time.time()

            def request(*args, **kwargs):
                # The renewed reservation keeps most of the 30-minute window.
                renewal_timeout_seconds = 1700
                assert kwargs["timeout"] > renewal_timeout_seconds
                with store.db() as c:
                    row = c.execute("select * from llm_admission").fetchone()
                    assert row["expires"] > now + 1800
                with self.assertRaises(Failure):
                    store.reserve_llm(1, now=now + 661)
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "issue_number": 0,
                                        "reason": "Distinct cause",
                                        "confidence": "low",
                                    }
                                )
                            }
                        }
                    ]
                }

            http.request.side_effect = request
            REQUEST_DEADLINE.at = time.monotonic() + 1800
            try:
                model.call("test", {}, MATCH_SCHEMA, time.monotonic() + 3600)
            finally:
                del REQUEST_DEADLINE.at
            assert http.request.call_count == 1


if __name__ == "__main__":
    unittest.main()
