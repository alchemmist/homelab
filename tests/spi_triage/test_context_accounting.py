"""Validated byte-bound contract; fixtures contain no production evidence."""

import copy
import json
import time
import unittest
from unittest.mock import Mock

import test_triage as f
from core import MATCH_SCHEMA, REPORT_SCHEMA, Failure
from integrations import Model


class ContextAccountingTests(unittest.TestCase):
    """Tests for SPI context accounting contracts."""

    def test_contract_and_schema_completion(self) -> None:

        'Verify the base contract schema is complete as shipped.'
        m = Model(Mock(), "unused")
        b = m.payload("x", {"text": 'é😀"\\\n' * 100}, MATCH_SCHEMA)
        n = m.reservation(b)
        b["max_tokens"] += 123
        assert m.reservation(b) == n + 123
        b["response_format"]["extra"] = "x" * 123
        assert m.reservation(b) > n + 246
        for change in (
            {"model": "other"},
            {"tools": []},
            {"chat_template_kwargs": {"enable_thinking": True}},
            {"messages": []},
        ):
            with self.assertRaises(Failure) as e:
                m.reservation({**b, **change})
            assert e.exception.code == "LLM_ACCOUNTING_CONTRACT_MISMATCH"
        m.http.request.assert_not_called()

    def test_excerpts_identity_reference_metadata_and_no_mutation(self) -> None:
        'Verify excerpt identity, references and metadata without mutation.'
        x = {
            "candidates": [{"number": n, "body": "😀" * 8000} for n in range(120)],
            "index": [{"id": "E001", "path": "original/reference", "excerpt": "x" * 40000}],
            "missing": [{"reason": "not collected"}],
            "truncated": True,
        }
        old = copy.deepcopy(x)
        v = Model.bounded_context(x)
        assert x == old
        assert [c["number"] for c in v["candidates"]] == list(range(120))
        assert v["index"][0]["id"] == "E001"
        assert v["index"][0]["path"] == "original/reference"
        assert v["missing"] == x["missing"]
        assert v["truncated"]
        for c in v["candidates"]:
            assert c["body"]["truncated"]
            assert c["body"]["unreviewed_bytes"] > 0

    def test_matching_event_bounded_and_all_identities(self) -> None:
        'Verify event matching stays bounded across all identities.'
        m = Model(Mock(), "unused")
        event = f.event()
        event["description"] = "x" * 1000000
        seen = []

        def call(task, data, schema, deadline) -> "dict[str, object]":
            assert m.reservation(m.payload(task, data, schema)) <= 30000
            assert data["alert"]["description"]["truncated"]
            seen.extend(x["number"] for x in data["open_issues"])
            return {"issue_number": 0, "reason": "No same problem.", "confidence": "low"}

        m.call = call
        m.match(event, [{"number": i, "body": "x" * 6000} for i in range(120)])
        assert seen == list(range(120))

    def test_large_analysis_preserves_candidates_and_artifact_index(self) -> None:
        'Verify large analyses preserve candidates and indexes.'
        m = Model(Mock(), "unused")
        event = f.event()
        event["description"] = "x" * 80000
        match = {
            "candidates": [{"number": n, "body": "report " * 5000} for n in range(3)],
            "reviewed_numbers": list(range(120)),
        }
        evidence = {
            "bundle": {
                "model_context": {
                    "index": [{"id": "E001", "path": "artifact/reference"}],
                    "excerpt": "evidence " * 5000,
                }
            },
            "missing": ["logs not collected"],
        }
        original = copy.deepcopy((event, match, evidence))
        captured = {}

        class Stop(Exception):
            pass

        def call(task, data, schema, deadline) -> "dict[str, object]":
            captured.update(data)
            assert m.budget_reservation(m.payload(task, data, schema)) <= 30000
            raise Stop()

        m.call = call
        with self.assertRaises(Stop):
            m.analyze(event, match, evidence)
        assert (event, match, evidence) == original
        assert [x["number"] for x in captured["preliminary_match"]["candidates"]] == [0, 1, 2]
        assert captured["preliminary_match"]["reviewed_numbers"] == list(range(120))
        assert captured["evidence"]["artifact_context"]["index"][0]["id"] == "E001"
        assert captured["alert"]["description"]["truncated"]

    def test_irreducible_metadata_visible_without_transport(self) -> None:
        'Verify irreducible metadata is visible without any transport.'
        m = Model(Mock(), "unused")
        event = f.event()
        event["path"] = ["x" * 120000] * 5
        with self.assertRaises(Failure) as e:
            m.analyze(event, {"candidates": []}, {})
        assert e.exception.code == "LLM_CONTEXT_METADATA_TOO_LARGE"
        m.http.request.assert_not_called()

    def test_local_120_long_report_analysis(self) -> None:
        'Verify a local 120-long report analysis completes cleanly.'
        if __import__("os").environ.get("SPI_TOKEN_ACCOUNTING_MODE") != "local-qwen-v1":
            return
        m = Model(Mock(), "unused")
        match = {
            "candidates": [{"number": n, "body": "report " * 5000} for n in range(120)],
            "reviewed_numbers": list(range(120)),
        }
        evidence = {
            "bundle": {
                "model_context": {
                    "index": [{"id": "E001", "path": "artifact/reference"}],
                    "excerpt": "evidence " * 5000,
                }
            }
        }
        original = copy.deepcopy((match, evidence))
        captured = {}

        class Stop(Exception):
            pass

        def call(task, data, schema, deadline) -> "dict[str, object]":
            captured.update(data)
            assert m.counter.reservation(m.payload(task, data, schema)) <= 30000
            raise Stop()

        m.call = call
        with self.assertRaises(Stop):
            m.analyze(f.event(), match, evidence)
        assert (match, evidence) == original
        assert [c["number"] for c in captured["preliminary_match"]["candidates"]] == list(range(120))
        assert captured["evidence"]["artifact_context"]["index"][0]["id"] == "E001"
