"""Isolated temporary SQLite only. No live cancellation or model requests."""

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
import test_triage as f
from core import Failure, Store
from queue_admin import QueueAdmin, authorized
from email.message import Message


class QueueAdminTests(unittest.TestCase):
    """Tests for SPI queue administration."""

    def setUp(self) -> None:

        'Create the queue fixture store and API.'
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "queue.sqlite")
        self.api = QueueAdmin(self.store)
        self.key = self.store.enqueue(f.event())["job_id"]

    def row(self) -> dict[str, object]:
        'Return the single queued row from the API list.'
        items = self.api.list({})["items"]
        value: dict[str, object] = next(x for x in items if x["id"] == self.key)
        return value

    def test_dedicated_auth_does_not_accept_worker_key_duplicates_or_non_ascii(self) -> None:
        'Verify dedicated auth rejects worker keys, dupes and non-ascii.'
        token = "local-fixture-" * 4
        headers = Message()
        headers["X-Worker-Token"] = token
        assert not authorized(headers, token)
        headers["X-Queue-Token"] = token
        assert authorized(headers, token)
        headers["X-Queue-Token"] = token
        assert not authorized(headers, token)
        other = Message()
        other["X-Queue-Token"] = "несовпадение"
        assert not authorized(other, token)
        assert not authorized(other, "")

    def test_minimal_dto_no_raw_event_result_or_fences(self) -> None:
        'Verify the DTO exposes no raw event, result or fences.'
        value = self.row()
        assert value["can_cancel"]
        assert value["state"] == "queued"
        assert value["failures"] == 0
        for field in ("event", "result", "intent", "fence", "request_fence", "response", "episode"):
            assert field not in value
        token_limit_per_minute = 30000
        assert self.api.list({})["limits"]["tokens_per_minute"] == token_limit_per_minute

    def test_cancel_preserves_row_checkpoint_budget_and_previous_error_audit(self) -> None:
        'Verify cancel preserves checkpoints, budget and error audit.'
        with self.store.db() as c:
            c.execute(
                "UPDATE jobs SET state='retry',error='GITHUB_READ_TIMEOUT',result=? WHERE id=?",
                (json.dumps({"safe_checkpoint": "retain"}), self.key),
            )
            c.execute("INSERT INTO job_failure_budget VALUES(?,3)", (self.key,))
        failure_budget_spent = 3
        value = self.row()
        result = self.api.cancel({"job_id": self.key, "expected_updated": value["updated"]})
        assert result["status"] == "cancelled"
        after = self.store.get(self.key)
        assert after["state"] == "cancelled"
        assert after["result"] == {"safe_checkpoint": "retain"}
        with self.store.db() as c:
            assert (
                c.execute(
                    "SELECT failures FROM job_failure_budget WHERE job_id=?", (self.key,)
                ).fetchone()[0]
                == failure_budget_spent
            )
            audit = c.execute("SELECT * FROM queue_operator_actions").fetchone()
            assert audit["previous_error"] == "GITHUB_READ_TIMEOUT"
            assert audit["previous_state"] == "retry"
        assert self.api.list({})["total"] == 0
        assert self.store.enqueue(f.event())["duplicate"] is True
        assert self.store.get(self.key)["state"] == "cancelled"

    def test_duplicate_cancel_has_one_audit_receipt(self) -> None:
        'Verify duplicate cancels produce exactly one audit receipt.'
        request = {"job_id": self.key, "expected_updated": self.row()["updated"]}
        self.api.cancel(request)
        assert self.api.cancel(request)["already_applied"]
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM queue_operator_actions").fetchone()[0] == 1

    def test_stale_version_rejected_after_claim(self) -> None:
        'Verify stale versions are rejected after claims.'
        item = self.row()
        self.store.claim()
        with self.assertRaises(Failure):
            self.api.cancel({"job_id": self.key, "expected_updated": item["updated"]})
        assert self.store.get(self.key)["state"] == "processing"

    def test_cancel_wins_then_claim_cannot_take_it(self) -> None:
        'Verify cancel wins and later claims cannot retake the job.'
        item = self.row()
        self.api.cancel({"job_id": self.key, "expected_updated": item["updated"]})
        assert not self.store.claim().get("job_id")

    def test_wait_owner_never_cancellable_even_if_job_is_retry(self) -> None:
        'Verify wait owners are never cancellable, even on retries.'
        self.store.claim()
        owner = self.store.owners.bind(self.key, "123", "durable-v1", "match", time.time())
        self.store.owners.defer(owner, "LLM_ADMISSION_DEFERRED", 61, time.time())
        with self.store.db() as c:
            c.execute("UPDATE jobs SET state='retry' WHERE id=?", (self.key,))
        item = self.row()
        assert not item["can_cancel"]
        with self.assertRaisesRegex(Failure, "QUEUE_ITEM_NOT_CANCELLABLE"):
            self.api.cancel({"job_id": self.key, "expected_updated": item["updated"]})

    def test_terminal_and_publication_states_are_not_cancellable(self) -> None:
        'Verify terminal and publication states are not cancellable.'
        for state, intent, issue, result in [
            ("complete", None, 0, {}),
            ("dead", None, 0, {}),
            ("cancelled", None, 0, {}),
            ("dry_run", None, 0, {}),
            ("retry", "{}", 0, {}),
            ("retry", None, 1, {}),
            ("retry", None, 0, {"primary_publication": {"id": 1}}),
        ]:
            with self.subTest(state=state, intent=intent, issue=issue, result=result):
                with self.store.db() as c:
                    c.execute(
                        "UPDATE jobs SET state=?,intent=?,issue=?,result=? WHERE id=?",
                        (state, intent, issue, json.dumps(result), self.key),
                    )
                current = self.store.get(self.key)
                with self.assertRaisesRegex(Failure, "QUEUE_ITEM_NOT_CANCELLABLE"):
                    self.api.cancel({"job_id": self.key, "expected_updated": current["updated"]})

    def test_audit_failure_rolls_back_cancellation(self) -> None:
        'Verify an audit failure rolls back the whole cancellation.'
        with self.store.db() as c:
            c.execute(
                "CREATE TRIGGER block_operator_audit BEFORE INSERT ON queue_operator_actions BEGIN SELECT RAISE(ABORT,'blocked'); END"
            )
        item = self.row()
        with self.assertRaisesRegex(sqlite3.IntegrityError, r"^blocked$"):
            self.api.cancel({"job_id": self.key, "expected_updated": item["updated"]})
        assert self.store.get(self.key)["state"] == "queued"

    def test_query_and_cancel_validation(self) -> None:
        'Verify query and cancel request validation.'
        for bad in (
            {"state": "all;DROP TABLE jobs"},
            {"limit": True},
            {"limit": 101},
            {"offset": -1},
        ):
            with self.assertRaisesRegex(Failure, "INVALID_QUEUE_QUERY"):
                self.api.list(bad)
        for bad in (
            {},
            {"job_id": self.key, "expected_updated": float("nan")},
            {"job_id": self.key, "expected_updated": True},
            {"job_id": "../", "expected_updated": 1},
        ):
            with self.assertRaisesRegex(Failure, "INVALID_QUEUE_CANCEL"):
                self.api.cancel(bad)


if __name__ == "__main__":
    unittest.main()
