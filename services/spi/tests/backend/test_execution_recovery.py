"""Offline regressions for the two reported executions. No external requests."""

import json
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import pytest
import test_triage as f
from core import OWNER_CONTEXT, REPORT_SCHEMA, Failure, Store
from integrations import Model
from test_wait_integration import IntegrationTests


class ReadWaitTests(IntegrationTests):
    def test_read_timeout_replays_receipt_then_resumes_after_restart(self):
        self.github.snapshot.side_effect = [Failure("GITHUB_READ_TIMEOUT", 60), []]
        sent = self.data
        response = self.engine.run_v1("match", sent)
        assert response["code"] == "GITHUB_READ_TIMEOUT"
        assert response["status"] == "deferred"
        assert response["deadline"] == sent["deadline"]
        assert self.engine.run_v1("match", sent) == response
        assert self.github.snapshot.call_count == 1
        self.engine.store = Store(self.store.path)
        self.engine.store.recover_on_start()
        self.now = response["due_at"]
        result = self.engine.run_v1("match", response)
        assert result["stage"] == "collect"
        assert self.store.get(self.key)["attempts"] == 1
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM job_failure_budget").fetchone()[0] == 0

    def test_github_network_error_waits_with_same_owner_and_survives_restart(self):
        import urllib.error
        from pathlib import Path

        from integrations import HTTP, GitHub

        token = Path(self.tmp.name) / "github-token"
        token.write_text("local-fixture-only")
        http = HTTP()
        http.opener = Mock()
        http.opener.open.side_effect = urllib.error.URLError(
            ConnectionResetError("private text must not escape")
        )
        self.engine.github = GitHub(http, str(token))
        sent = self.data
        response = self.engine.run_v1("match", sent)
        assert response["code"] == "GITHUB_READ_NETWORK_ERROR"
        assert response["status"] == "deferred"
        assert response["deadline"] == sent["deadline"]
        assert response["execution_id"] == sent["execution_id"]
        assert "private text" not in json.dumps(response)
        self.model.match.assert_not_called()
        assert self.engine.run_v1("match", sent) == response
        assert http.opener.open.call_count == 1
        assert self.store.claim() == {"job_id": ""}
        self.engine.store = Store(self.store.path)
        self.engine.store.recover_on_start()
        self.now = response["due_at"]
        self.engine.github = Mock()
        self.engine.github.snapshot.return_value = []
        result = self.engine.run_v1("match", response)
        assert result["stage"] == "collect"
        self.model.match.assert_called_once()
        assert self.store.get(self.key)["attempts"] == 1
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM job_failure_budget").fetchone()[0] == 0
            assert c.execute("SELECT count(*) FROM llm_admission").fetchone()[0] == 0
        with pytest.raises(Failure):
            self.engine.run_v1("match", sent)

    def test_github_network_wait_does_not_extend_absolute_deadline(self):
        with self.store.db() as c:
            c.execute(
                "UPDATE workflow_wait_owner SET deadline=? WHERE job_id=?",
                (self.now + 100, self.key),
            )
        self.github.snapshot.side_effect = Failure("GITHUB_READ_NETWORK_ERROR", 60)
        with pytest.raises(Failure, match="WAIT_DEADLINE_EXCEEDED"):
            self.engine.run_v1("match", self.data)
        with self.store.db() as c:
            assert (
                c.execute(
                    "SELECT phase FROM workflow_wait_owner WHERE job_id=?", (self.key,)
                ).fetchone()[0]
                == "failed"
            )
        self.model.match.assert_not_called()

    def test_graph_capture_budget_resumes_same_collect_owner_without_paid_replay(self):
        sent = self.engine.run_v1("match", self.data)
        self.evidence.collect.side_effect = [Failure("GRAPH_CAPTURE_DEFERRED", 1), {"missing": []}]
        waiting = self.engine.run_v1("collect", sent)
        assert waiting["status"] == "deferred"
        assert waiting["code"] == "GRAPH_CAPTURE_DEFERRED"
        assert waiting["deadline"] == sent["deadline"]
        assert self.engine.run_v1("collect", sent) == waiting
        assert self.evidence.collect.call_count == 1
        self.engine.store = Store(self.store.path)
        self.engine.store.recover_on_start()
        self.now = waiting["due_at"]
        result = self.engine.run_v1("collect", waiting)
        assert result["stage"] == "analyze"
        assert self.model.match.call_count == 1
        self.model.analyze.assert_not_called()
        with self.store.db() as c:
            assert c.execute("select count(*) from job_failure_budget").fetchone()[0] == 0


class MatchSliceTests(IntegrationTests):
    def exercise(self, nominees=False):
        from test_large_spi_catalog import LargeCatalogTests

        rows = LargeCatalogTests.issues(151)
        self.github.snapshot.return_value = rows
        self.github.open_signature.return_value = f.digest(
            [(x["number"], x["updated_at"]) for x in rows]
        )
        model = Model(Mock(), "fixture-only", store=self.store)
        batches = []

        def paid(task, data, schema, deadline):
            # A single paid batch is fast enough; the whole catalog is not.
            assert deadline - self.now >= 1799
            self.now += 200
            ids = [x["number"] for x in data["open_issues"]]
            batches.append(ids)
            return {
                "issue_number": ids[0] if nominees else 0,
                "reason": "fixture",
                "confidence": "low",
            }

        model.call = Mock(side_effect=paid)
        self.engine.model = model
        deadline = self.data["deadline"]
        waits = 0
        with patch("time.monotonic", lambda: self.now):
            while True:
                sent = self.data
                self.data = self.engine.run_v1("match", sent)
                if self.data["status"] != "deferred":
                    break
                waits += 1
                assert self.data["code"] == "MATCH_PROGRESS_DEFERRED"
                assert self.data["deadline"] == deadline
                calls = model.call.call_count
                assert self.engine.run_v1("match", sent) == self.data
                assert model.call.call_count == calls
                assert self.store.claim() == {"job_id": ""}
                self.store = Store(self.store.path)
                self.store.recover_on_start()
                self.engine.store = model.store = self.store
                self.now = self.data["due_at"]
                assert waits < 30
        assert self.data["stage"] == "collect"
        assert [n for batch in batches[:13] for n in batch] == list(range(1, 152))
        assert len(batches) == (25 if nominees else 13)
        assert waits == len(batches) - 1
        self.github.snapshot.assert_called_once()  # no repeated per-issue comments
        assert self.store.get(self.key)["attempts"] == 1
        with self.store.db() as c:
            assert c.execute("SELECT count(*) FROM job_failure_budget").fetchone()[0] == 0

    def test_large_match_uses_fresh_bounded_requests_without_repaying_reviews(self):
        self.exercise()

    def test_pairwise_nominee_reduction_is_also_checkpointed_between_calls(self):
        self.exercise(nominees=True)

    def test_model_timeout_requeues_once_without_paging(self):
        import contextlib
        import io

        self.model.match.side_effect = Failure("LLM_UPSTREAM_TIMEOUT")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.engine.run_v1("match", self.data)
        assert result == {"contract": 1, "status": "empty", "job_id": ""}
        assert self.store.get(self.key)["state"] == "retry"
        records = [json.loads(x) for x in output.getvalue().splitlines()]
        assert "stage_failed" not in [x["event"] for x in records]
        deferred = next(x for x in records if x["event"] == "stage_deferred")
        assert deferred["code"] == "LLM_UPSTREAM_TIMEOUT"
        assert "job_id" not in deferred
        self.model.match.assert_called_once()
        with self.store.db() as c:
            assert (
                c.execute(
                    "SELECT phase FROM workflow_wait_owner WHERE job_id=?", (self.key,)
                ).fetchone()[0]
                == "failed"
            )

    def test_changed_fingerprint_fetches_fresh_snapshot_instead_of_cached_excerpts(self):
        from test_large_spi_catalog import LargeCatalogTests

        rows = LargeCatalogTests.issues(24)
        self.github.snapshot.return_value = rows
        self.github.open_signature.return_value = "changed"
        model = Model(Mock(), "fixture-only", store=self.store)
        model.call = Mock(
            return_value={"issue_number": 0, "reason": "fixture", "confidence": "low"}
        )
        self.engine.model = model
        self.data = self.engine.run_v1("match", self.data)
        self.now = self.data["due_at"]
        self.data = self.engine.run_v1("match", self.data)
        assert self.github.snapshot.call_count == 2
        assert model.call.call_count == 2
        assert self.data["stage"] == "collect"


@patch.dict("os.environ", {"SPI_TOKEN_ACCOUNTING_MODE": "byte-bound-v1"})
class RepairTests(unittest.TestCase):
    def test_repair_budget_survives_admission_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp + "/db")
            key = store.enqueue(f.event())["job_id"]
            OWNER_CONTEXT.binding = (key, "test-fence")
            bad = f.report()
            bad["facts"] = ["Unknown [E999]"]
            good = f.report()
            good["facts"] = ["Verified [E001]."]
            data = {"evidence": {"artifact_context": {"index": [{"id": "E001"}]}}}
            http = Mock()
            http.request.return_value = {"choices": [{"message": {"content": json.dumps(bad)}}]}
            try:
                with (
                    patch.object(
                        store, "reserve_llm", side_effect=[1, Failure("LLM_ADMISSION_DEFERRED", 61)]
                    ),
                    patch.object(store, "finish_llm"),
                ):
                    with pytest.raises(Failure, match="LLM_ADMISSION_DEFERRED"):
                        Model(http, "fake", store=store).call(
                            "analysis", data, REPORT_SCHEMA, time.monotonic() + 20
                        )
                assert http.request.call_count == 1
                store = Store(store.path)
                with store.db() as c:
                    assert (
                        c.execute("SELECT failures FROM analysis_output_budget").fetchone()[0] == 1
                    )
                http.request.return_value = {
                    "choices": [{"message": {"content": json.dumps(good)}}]
                }
                with (
                    patch.object(store, "reserve_llm", return_value=2),
                    patch.object(store, "finish_llm"),
                ):
                    assert (
                        Model(http, "fake", store=store).call(
                            "analysis", data, REPORT_SCHEMA, time.monotonic() + 20
                        )
                        == good
                    )
                assert (
                    "Previous output failed"
                    in http.request.call_args.args[3]["messages"][1]["content"]
                )
                # Conservative crash recovery: consumed repair cannot be repeated,
                # even if its valid answer was lost before the report checkpoint.
                store = Store(store.path)
                with pytest.raises(Failure, match="LLM_INVALID_EVIDENCE_REFERENCE"):
                    Model(http, "fake", store=store).call(
                        "analysis", data, REPORT_SCHEMA, time.monotonic() + 20
                    )
                assert http.request.call_count == 2
            finally:
                del OWNER_CONTEXT.binding
