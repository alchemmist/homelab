"""Snapshot refresh stays in one v1 execution; only local mock fixtures."""

import unittest
from unittest.mock import patch

import test_triage as f
import test_wait_integration as integration_fixtures
from core import Failure, Store


class SnapshotOwnerRestartTests(unittest.TestCase):
    """Tests for snapshot ownership across restarts."""

    setUp = integration_fixtures.IntegrationTests.setUp
    tearDown = integration_fixtures.IntegrationTests.tearDown

    def to_analyze(self) -> dict[str, object]:
        """Advance a fresh event through matching."""
        data = self.engine.run_v1("match", self.data)
        result: dict[str, object] = self.engine.run_v1("collect", data)
        return result

    def test_early_snapshot_change_rewinds_same_execution_without_paid_analysis(
        self,
    ) -> None:
        """Verify early snapshot changes rewind without paid analysis."""
        sent = self.to_analyze()
        deadline = sent["deadline"]
        self.github.open_signature.return_value = "changed"
        ready = self.engine.run_v1("analyze", sent)
        assert (ready["status"], ready["stage"], ready["execution_id"]) == (
            "ready",
            "match",
            "1234",
        )
        assert ready["deadline"] == deadline
        assert ready["fence"] != sent["fence"]
        self.model.analyze.assert_not_called()
        assert self.engine.run_v1("analyze", sent) == ready
        assert self.store.get(self.key)["attempts"] == 1
        assert self.store.get(self.key)["state"] == "processing"
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM job_failure_budget").fetchone()[0] == 0
        self.store = Store(self.store.path)
        self.engine.store = self.store
        assert self.store.recover_on_start() == 0
        assert self.engine.claim(self.identity) == ready
        self.github.open_signature.return_value = f.digest([])
        for stage in ("match", "collect", "analyze", "publish"):
            ready = self.engine.run_v1(stage, ready)
        assert ready["status"] == "complete"
        assert self.github.request.call_count == 1

    def test_expensive_snapshot_churn_keeps_original_two_replacement_limit(
        self,
    ) -> None:
        """Verify snapshot churn keeps the two-replacement limit."""
        data = self.data
        deadline = data["deadline"]
        for generation in range(3):
            self.github.open_signature.return_value = f.digest([])
            for stage in ("match", "collect", "analyze"):
                data = self.engine.run_v1(stage, data)
            self.github.snapshot.return_value = [{"number": 9, "updated_at": "changed"}]
            if generation == 2:
                with self.assertRaisesRegex(Failure, "WRITE_NEEDS_REVIEW"):
                    self.engine.run_v1("publish", data)
                break
            sent = data
            data = self.engine.run_v1("publish", sent)
            assert (data["status"], data["stage"]) == ("ready", "match")
            assert data["deadline"] == deadline
            assert self.engine.run_v1("publish", sent) == data
            self.github.snapshot.return_value = []
        job = self.store.get(self.key)
        assert (job["state"], job["error"]) == ("dead", "WRITE_NEEDS_REVIEW")
        # Only two snapshot replacements are budgeted: the third generation is refused.
        replacement_limit = 2
        with self.store.db() as c:
            assert (
                c.execute(
                    "SELECT replacements FROM snapshot_budget WHERE job_id=?",
                    (self.key,),
                ).fetchone()[0]
                == replacement_limit
            )
        self.github.request.assert_not_called()

    def test_job_and_owner_rewind_roll_back_together_on_receipt_failure(self) -> None:
        """Verify job and owner rewind together on receipt failure."""
        data = self.to_analyze()
        with self.store.db() as c:
            before_job = tuple(
                c.execute("SELECT stage,result,state FROM jobs WHERE id=?", (self.key,)).fetchone()
            )
            before_owner = tuple(
                c.execute(
                    "SELECT stage,fence,phase FROM workflow_wait_owner WHERE job_id=?",
                    (self.key,),
                ).fetchone()
            )
        # Direct transaction exercise; do not run generic fail() after the injected fault.
        from core import OWNER_CONTEXT

        _, owner = self.store.owners.begin("analyze", data, self.now)
        OWNER_CONTEXT.binding = (self.key, owner["fence"])
        try:
            job = self.store.get(self.key)
            with (
                patch.object(
                    self.store.owners,
                    "snapshot_replaced",
                    side_effect=RuntimeError("local fixture"),
                ),
                self.assertRaises(RuntimeError),
            ):
                self.store.replace_snapshot(self.key, job, {}, False)
        finally:
            del OWNER_CONTEXT.binding
        with self.store.db() as c:
            assert (
                tuple(
                    c.execute(
                        "SELECT stage,result,state FROM jobs WHERE id=?", (self.key,)
                    ).fetchone()
                )
                == before_job
            )
            row = c.execute(
                "SELECT stage,fence,phase FROM workflow_wait_owner WHERE job_id=?",
                (self.key,),
            ).fetchone()
            assert (row["stage"], row["fence"]) == before_owner[:2]
            assert row["phase"] == "running"


if __name__ == "__main__":
    unittest.main()
