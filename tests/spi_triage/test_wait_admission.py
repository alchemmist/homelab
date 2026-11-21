"""Admission regressions: local fixtures only; no inference or network."""

import concurrent.futures
import tempfile
import unittest
from unittest.mock import Mock, patch
import test_triage as f
from core import Store
from service import Engine


class OwnerAdmissionTests(unittest.TestCase):
    def setUp(self):
        """Create the wait scheduling fixture."""
        self.now = 1000
        self.clock = patch("time.time", lambda: self.now)
        self.clock.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name + "/db")
        self.github = Mock()
        self.github.snapshot.return_value = []
        self.github.open_signature.return_value = f.digest([])
        self.model = Mock()
        self.model.match.return_value = {"candidates": []}
        self.engine = Engine(self.store, self.github, self.model, Mock())
        self.key = self.store.enqueue(f.event())["job_id"]
        self.data = self.engine.claim(self.identity("100"))

    def tearDown(self):
        """Stop the wait scheduling clock."""
        self.clock.stop()
        self.tmp.cleanup()

    @staticmethod
    def identity(execution):
        """Build a wait identity for the given execution."""
        return {"execution_id": execution, "workflow_revision": "durable-v1"}

    def waiting(self):
        """Hold the engine lock to simulate a waiting owner."""
        self.engine.lock.acquire()
        try:
            return self.engine.run_v1("match", self.data)
        finally:
            self.engine.lock.release()

    def queued(self):
        """Enqueue a fresh event and return its job key."""
        return self.store.enqueue(f.event(start="2026-11-03T14:00:00Z"))["job_id"]

    def test_wait_is_not_a_free_slot_for_another_claim(self):
        """Verify a waiting owner's slot is not stolen by new claims."""
        waiting = self.waiting()
        key = self.queued()
        with self.store.db() as c:
            self.assertEqual(
                c.execute("SELECT lease FROM jobs WHERE id=?", (self.key,)).fetchone()[0], 0
            )
        self.assertEqual(self.engine.claim(self.identity("101"))["status"], "empty")
        self.assertEqual(self.store.claim(), {"job_id": ""})
        self.assertEqual(self.store.get(key)["state"], "queued")
        self.assertEqual(self.store.get(key)["attempts"], 0)
        self.assertEqual(self.engine.claim(self.identity("100"))["fence"], waiting["fence"])
        self.model.match.assert_not_called()

    def test_dispatch_does_not_launch_empty_callbacks_while_owner_waits(self):
        """Verify dispatch launches no empty callbacks during owner waits."""
        waiting = self.waiting()
        self.queued()
        token, due = self.store.reserve_dispatch(self.now)
        self.assertIsNone(token)
        self.assertEqual(due, waiting["due_at"] + 180)

    def test_concurrent_new_claims_cannot_fill_owner_wait_queue(self):
        """Verify concurrent claims cannot fill an owner wait queue."""
        self.waiting()
        key = self.queued()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(
                pool.map(
                    lambda execution: self.engine.claim(self.identity(execution)), ["101", "102"]
                )
            )
        self.assertEqual([r["status"] for r in results], ["empty", "empty"])
        self.assertEqual(self.store.get(key)["attempts"], 0)
        with self.store.db() as c:
            self.assertEqual(
                c.execute(
                    "SELECT count(*) FROM workflow_wait_owner WHERE phase IN ('ready','waiting','running')"
                ).fetchone()[0],
                1,
            )

    def test_existing_older_match_owner_wins_even_just_before_wake(self):
        """Verify the older match owner wins even right before wake."""
        # Seed a valid pre-upgrade cohort, not a new claim permitted by policy.
        older = self.waiting()
        key = self.queued()
        self.now += 1
        with self.store.db() as c:
            c.execute(
                "UPDATE jobs SET state='processing',lease=0,updated=? WHERE id=?", (self.now, key)
            )
        self.store.owners.bind(key, "101", "durable-v1", "match", self.now)
        with self.store.db() as c:
            c.execute(
                "UPDATE workflow_wait_owner SET phase='ready',expires=? WHERE job_id=?",
                (self.now + 180, key),
            )
            younger = self.store.owners.envelope(
                c.execute("SELECT * FROM workflow_wait_owner WHERE job_id=?", (key,)).fetchone()
            )
        younger = self.engine.run_v1("match", younger)
        self.assertEqual(younger["status"], "deferred")
        self.model.match.assert_not_called()
        self.now = older["due_at"]
        result = self.engine.run_v1("match", older)
        self.assertEqual(result["stage"], "collect")
        self.assertEqual(self.model.match.call_count, 1)
        self.assertEqual(self.store.get(key)["stage"], 0)


if __name__ == "__main__":
    unittest.main()
