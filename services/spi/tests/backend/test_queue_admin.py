"""Isolated temporary SQLite only. No live cancellation or model requests."""

import hashlib
import json
import tempfile
import time
import unittest
from email.message import Message
from pathlib import Path

import pytest
import test_triage as f
from core import Failure, Store
from queue_admin import QueueAdmin, authorized


class QueueAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "queue.sqlite")
        self.api = QueueAdmin(self.store)
        self.key = self.store.enqueue(f.event())["job_id"]

    def row(self):
        return next(x for x in self.api.list({})["items"] if x["id"] == self.key)

    def test_dedicated_auth_does_not_accept_worker_key_duplicates_or_non_ascii(self):
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

    def test_minimal_dto_no_raw_event_result_or_fences(self):
        value = self.row()
        assert value["can_cancel"]
        assert value["state"] == "queued"
        assert value["failures"] == 0
        for field in ("event", "result", "intent", "fence", "request_fence", "response", "episode"):
            assert field not in value
        assert self.api.list({})["limits"]["tokens_per_minute"] == 30000

    def test_cancel_preserves_row_checkpoint_budget_and_previous_error_audit(self):
        with self.store.db() as c:
            c.execute(
                "UPDATE jobs SET state='retry',error='GITHUB_READ_TIMEOUT',result=? WHERE id=?",
                (json.dumps({"safe_checkpoint": "retain"}), self.key),
            )
            c.execute("INSERT INTO job_failure_budget VALUES(?,3)", (self.key,))
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
                == 3
            )
            audit = c.execute("SELECT * FROM queue_operator_actions").fetchone()
            assert audit["previous_error"] == "GITHUB_READ_TIMEOUT"
            assert audit["previous_state"] == "retry"
        assert self.api.list({})["total"] == 0
        assert self.store.enqueue(f.event())["duplicate"] == True
        assert self.store.get(self.key)["state"] == "cancelled"

    def test_duplicate_cancel_has_one_audit_receipt(self):
        request = {"job_id": self.key, "expected_updated": self.row()["updated"]}
        self.api.cancel(request)
        assert self.api.cancel(request)["already_applied"]
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM queue_operator_actions").fetchone()[0] == 1

    def test_stale_version_rejected_after_claim(self):
        item = self.row()
        self.store.claim()
        with pytest.raises(Failure):
            self.api.cancel({"job_id": self.key, "expected_updated": item["updated"]})
        assert self.store.get(self.key)["state"] == "processing"

    def test_cancel_wins_then_claim_cannot_take_it(self):
        item = self.row()
        self.api.cancel({"job_id": self.key, "expected_updated": item["updated"]})
        assert not self.store.claim().get("job_id")

    def test_wait_owner_never_cancellable_even_if_job_is_retry(self):
        self.store.claim()
        owner = self.store.owners.bind(self.key, "123", "durable-v1", "match", time.time())
        self.store.owners.defer(owner, "LLM_ADMISSION_DEFERRED", 61, time.time())
        with self.store.db() as c:
            c.execute("UPDATE jobs SET state='retry' WHERE id=?", (self.key,))
        item = self.row()
        assert not item["can_cancel"]
        with pytest.raises(Failure, match="QUEUE_ITEM_NOT_CANCELLABLE"):
            self.api.cancel({"job_id": self.key, "expected_updated": item["updated"]})

    def test_terminal_and_publication_states_are_not_cancellable(self):
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
                with pytest.raises(Failure, match="QUEUE_ITEM_NOT_CANCELLABLE"):
                    self.api.cancel({"job_id": self.key, "expected_updated": current["updated"]})

    def test_audit_failure_rolls_back_cancellation(self):
        with self.store.db() as c:
            if self.store.pg_url:
                c.execute(
                    "CREATE FUNCTION refuse() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture'; END $$"
                )
                c.execute(
                    "CREATE TRIGGER block_operator_audit BEFORE INSERT ON queue_operator_actions FOR EACH ROW EXECUTE FUNCTION refuse()"
                )
            else:
                c.execute(
                    "CREATE TRIGGER block_operator_audit BEFORE INSERT ON queue_operator_actions BEGIN SELECT RAISE(ABORT,'blocked'); END"
                )
        item = self.row()
        with pytest.raises(Exception):
            self.api.cancel({"job_id": self.key, "expected_updated": item["updated"]})
        assert self.store.get(self.key)["state"] == "queued"

    def seed_ordering(self):
        keys = [self.key]
        for n in range(1, 12):
            value = f.event()
            value["event_key"] = hashlib.sha256(str(n).encode()).hexdigest()
            value["episode"] = value["event_key"]
            keys.append(self.store.enqueue(value)["job_id"])
        with self.store.db() as c:
            for n, key in enumerate(keys):
                event = json.loads(
                    c.execute("SELECT event FROM jobs WHERE id=?", (key,)).fetchone()[0]
                )
                event["labels"]["alertname"] = ["Zulu", "alpha", "Alpha", "Beta"][n % 4]
                c.execute(
                    "UPDATE jobs SET created=?,event=?,stage=?,attempts=?,state=?,result=? WHERE id=?",
                    (
                        100 + n // 2,
                        json.dumps(event),
                        n % 4,
                        n % 3,
                        ("queued", "retry", "processing")[n % 3],
                        json.dumps(
                            {"match_progress_v3": {"reviews": [{}] * (n % 4), "snapshot": []}}
                        ),
                        key,
                    ),
                )
                c.execute("INSERT OR REPLACE INTO job_failure_budget VALUES(?,?)", (key, n % 2))
        return keys

    def test_default_oldest_created_not_stage_or_processing_priority(self):
        self.seed_ordering()
        rows = self.api.list({})["items"]
        assert [(r["created"], r["id"]) for r in rows] == sorted(
            (r["created"], r["id"]) for r in rows
        )
        assert self.api.list({})["sort"] == "created"
        assert self.api.list({})["direction"] == "asc"

    def test_cursor_all_sorts_directions_exact_ties_and_global_order(self):
        self.seed_ordering()
        for sort in ("created", "alert", "state", "progress"):
            for direction in ("asc", "desc"):
                query = {"sort": sort, "direction": direction, "limit": 3}
                expected = self.api.list({**query, "limit": 100})["items"]
                seen = []
                for _ in range(10):
                    page = self.api.list(query)
                    seen.extend(page["items"])
                    if page["next_cursor"] is None:
                        break
                    query["after"] = page["next_cursor"]
                else:
                    self.fail("Cursor failed to terminate")
                assert [r["id"] for r in seen] == [r["id"] for r in expected]
                assert len({r["id"] for r in seen}) == 12
                if sort == "alert":
                    names = [r["alertname"].lower() for r in seen]
                    assert names == sorted(names, reverse=direction == "desc")
                if sort == "state":
                    rank = {"queued": 0, "retry": 1, "processing": 2}
                    order = [(rank[r["state"]], r["stage"], r["created"], r["id"]) for r in seen]
                    assert order == sorted(order, reverse=direction == "desc")
                if sort == "progress":
                    order = [
                        (
                            r["review_batches"] or 0,
                            r["attempts"],
                            r["failures"],
                            r["created"],
                            r["id"],
                        )
                        for r in seen
                    ]
                    assert order == sorted(order, reverse=direction == "desc")

    def test_created_cursor_does_not_skip_after_earlier_cancellation_or_new_arrival(self):
        self.seed_ordering()
        first = self.api.list({"limit": 3})
        row = first["items"][0]
        self.api.cancel({"job_id": row["id"], "expected_updated": row["updated"]})
        value = f.event()
        value["event_key"] = hashlib.sha256(b"new").hexdigest()
        value["episode"] = value["event_key"]
        new = self.store.enqueue(value)["job_id"]
        following = self.api.list({"after": first["next_cursor"], "limit": 100})["items"]
        assert len(following) == 10
        assert len(set(r["id"] for r in first["items"] + following)) == 13
        assert new in [r["id"] for r in following]

    def test_invalid_cursor_order_values_and_sql_are_rejected(self):
        self.seed_ordering()
        cursor = self.api.list({"limit": 2})["next_cursor"]
        for query in (
            {"sort": "created;DROP TABLE jobs"},
            {"direction": "desc;--"},
            {"after": {**cursor, "sort": "alert"}},
            {"offset": 1, "after": cursor},
            {"after": {**cursor, "values": [True, "a" * 64]}},
            {"after": {**cursor, "values": [float("inf"), "a" * 64]}},
            {"after": {**cursor, "values": [1, "../"]}},
            {"after": []},
            {"after": {**cursor, "values": [1]}},
        ):
            with self.subTest(query=query), pytest.raises(Failure, match="INVALID_QUEUE_QUERY"):
                self.api.list(query)
        assert self.api.list({})["total"] == 12

    def seed_batch(self, count):
        event = json.dumps(f.event())
        values = [
            (hashlib.sha256(("batch" + str(n)).encode()).hexdigest(), event) for n in range(count)
        ]
        with self.store.db() as c:
            c.executemany(
                "INSERT INTO jobs(id,episode,event,created,updated,available,result,state) VALUES(?,? ,?,1,1,1,?, 'queued')",
                [(key, key, event, json.dumps({"safe_checkpoint": key})) for key, event in values],
            )
        return [{"job_id": key, "expected_updated": 1} for key, _ in values]

    def test_bulk_400_one_transaction_preserves_history_and_is_idempotent(self):
        from unittest.mock import patch

        batch = self.seed_batch(400)
        with patch.object(self.store, "db", wraps=self.store.db) as transactions:
            result = self.api.cancel_batch({"items": batch})
        assert transactions.call_count == 1
        assert len(result["cancelled"]) == 400
        assert result["skipped"] == []
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM queue_operator_actions").fetchone()[0] == 400
            assert (
                c.execute(
                    "SELECT count(*) FROM jobs WHERE state='cancelled' AND json_extract(result,'$.safe_checkpoint')=id"
                ).fetchone()[0]
                == 400
            )
            assert c.execute("SELECT count(*) FROM jobs").fetchone()[0] == 401
        again = self.api.cancel_batch({"items": batch})
        assert len(again["already_cancelled"]) == 400
        assert again["cancelled"] == []
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM queue_operator_actions").fetchone()[0] == 400
        assert self.store.get(self.key)["state"] == "queued"  # unselected arrival untouched

    def test_bulk_skips_changed_owned_and_publication_rows_in_same_commit(self):
        self.store.claim()
        owner = self.store.owners.bind(self.key, "123", "durable-v1", "match", time.time())
        self.store.owners.defer(owner, "LLM_ADMISSION_DEFERRED", 61, time.time())
        batch = self.seed_batch(6)
        with self.store.db() as c:
            c.execute("UPDATE jobs SET updated=2 WHERE id=?", (batch[0]["job_id"],))
            c.execute("UPDATE jobs SET state='processing' WHERE id=?", (batch[1]["job_id"],))
            c.execute("UPDATE jobs SET intent='{}' WHERE id=?", (batch[2]["job_id"],))
            c.execute(
                "UPDATE jobs SET result=? WHERE id=?",
                (json.dumps({"primary_publication": {"id": 1}}), batch[3]["job_id"]),
            )
            c.execute("UPDATE jobs SET issue=123 WHERE id=?", (batch[4]["job_id"],))
        row = self.store.get(self.key)
        result = self.api.cancel_batch(
            {
                "items": batch
                + [
                    {"job_id": self.key, "expected_updated": row["updated"]},
                    {"job_id": "f" * 64, "expected_updated": 1},
                ]
            }
        )
        assert result["cancelled"] == [batch[5]["job_id"]]
        assert len(result["skipped"]) == 7
        assert "QUEUE_ITEM_CHANGED" in [r["code"] for r in result["skipped"]]
        assert "JOB_NOT_FOUND" in [r["code"] for r in result["skipped"]]
        assert self.store.get(self.key)["state"] == "processing"

    def test_bulk_audit_error_rolls_back_entire_batch(self):
        batch = self.seed_batch(10)
        with self.store.db() as c:
            if self.store.pg_url:
                c.execute(
                    "CREATE FUNCTION refuse() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture'; END $$"
                )
                c.execute(
                    "CREATE TRIGGER block_batch_audit BEFORE INSERT ON queue_operator_actions FOR EACH ROW WHEN (NEW.job_id='"
                    + batch[5]["job_id"]
                    + "') EXECUTE FUNCTION refuse()"
                )
            else:
                c.execute(
                    "CREATE TRIGGER block_batch_audit BEFORE INSERT ON queue_operator_actions WHEN NEW.job_id='"
                    + batch[5]["job_id"]
                    + "' BEGIN SELECT RAISE(ABORT,'fixture'); END"
                )
        with pytest.raises(Exception):
            self.api.cancel_batch({"items": batch})
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM jobs WHERE state='cancelled'").fetchone()[0] == 0
            assert c.execute("SELECT count(*) FROM queue_operator_actions").fetchone()[0] == 0

    def test_bulk_rejects_invalid_or_duplicate_input_without_partial_writes(self):
        batch = self.seed_batch(1)
        for bad in (
            {},
            {"items": []},
            {"items": batch * 4001},
            {"items": batch * 2},
            {"items": batch + [{"job_id": "bad", "expected_updated": 1}]},
            {"items": [{"job_id": self.key, "expected_updated": True}]},
            {"items": [{"job_id": self.key, "expected_updated": float("nan")}]},
            {"items": [{"job_id": self.key, "expected_updated": 2**13000}]},
            {"items": batch, "state": "pending"},
        ):
            with pytest.raises(Failure, match="INVALID_QUEUE_CANCEL_BATCH"):
                self.api.cancel_batch(bad)
        assert self.store.get(batch[0]["job_id"])["state"] == "queued"

    def test_bulk_maximum_stays_inside_fixed_http_body_and_response_bounds(self):
        from queue_admin import MAX_CANCEL_BATCH

        batch = self.seed_batch(MAX_CANCEL_BATCH)
        assert len(json.dumps({"items": batch}).encode()) < 512000
        with self.store.db() as c:
            c.execute("UPDATE jobs SET state='processing'")
        result = self.api.cancel_batch({"items": batch})
        assert len(result["skipped"]) == MAX_CANCEL_BATCH
        assert len(json.dumps(result).encode()) < 512000

    def test_query_and_cancel_validation(self):
        for bad in (
            {"state": "all;DROP TABLE jobs"},
            {"limit": True},
            {"limit": 101},
            {"offset": -1},
        ):
            with pytest.raises(Failure, match="INVALID_QUEUE_QUERY"):
                self.api.list(bad)
        for bad in (
            {},
            {"job_id": self.key, "expected_updated": float("nan")},
            {"job_id": self.key, "expected_updated": True},
            {"job_id": "../", "expected_updated": 1},
        ):
            with pytest.raises(Failure, match="INVALID_QUEUE_CANCEL"):
                self.api.cancel(bad)


if __name__ == "__main__":
    unittest.main()
