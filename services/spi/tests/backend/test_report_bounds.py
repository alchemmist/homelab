"""Offline regression for17941: bounded generation, never partial-report salvage."""

import copy
import json
import time
import unittest
from unittest.mock import Mock, patch

import pytest
import test_triage as f
from core import MATCH_SCHEMA, REPORT_SCHEMA, Failure, validate
from integrations import Model
from report_bounds import ARRAY_LIMITS, TEXT_LIMITS, guided_report_schema


def maximal(schema):
    out = {}
    for key, p in schema["properties"].items():
        if "enum" in p:
            out[key] = max(p["enum"], key=lambda x: len(str(x)))
        elif p["type"] == "integer":
            out[key] = p["maximum"]
        elif p["type"] == "array":
            out[key] = ["!" * p["items"]["maxLength"]] * p["maxItems"]
        else:
            out[key] = "!" * p["maxLength"]
    return out


@patch.dict("os.environ", {"SPI_TOKEN_ACCOUNTING_MODE": "byte-bound-v1"})
class ReportBoundsTests(unittest.TestCase):
    def model(self):
        return Model(Mock(), "test-only", store=Mock())

    def test_every_variable_prose_field_is_bounded_before_generation(self):
        before = copy.deepcopy(REPORT_SCHEMA)
        m = self.model()
        body = m.payload("analysis", {}, REPORT_SCHEMA)
        schema = body["response_format"]["json_schema"]["schema"]
        for key, limit in TEXT_LIMITS.items():
            assert schema["properties"][key]["maxLength"] == limit
        for key, (count, length) in ARRAY_LIMITS.items():
            assert schema["properties"][key]["maxItems"] == count
            assert schema["properties"][key]["items"]["maxLength"] == length
        assert body["max_tokens"] == 2500
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        # This decoder ignores maxLength with pattern, and crashes with
        # multiple bounded pattern fields. Prose must use maxLength alone.
        assert "pattern" not in schema["properties"]["summary"]
        assert "{1,120}" in schema["properties"]["facts"]["items"]["pattern"]
        assert REPORT_SCHEMA == before
        assert m.payload("match", {}, MATCH_SCHEMA)["max_tokens"] == 768
        m.http.request.assert_not_called()

    def test_worst_canonical_completion_fits_without_any_bpe_merges(self):
        schema = guided_report_schema(issue_numbers=[2147483647])
        value = maximal(schema)
        validate(value, schema)
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("ascii")
        # Conservative byte-level upper bound: output BPE merges can only help.
        assert len(raw) <= 2200
        assert len(raw) < self.model().payload("x", {}, REPORT_SCHEMA)["max_tokens"]

    def test_fact_reference_and_prose_bounds_are_both_required(self):
        schema = guided_report_schema(["E007"])
        value = f.report()
        value["facts"] = ["Observation [E007]."]
        validate(value, schema)
        for fact in ("Observation [E999].", "Uncited observation.", "x" * 121 + " [E007]."):
            value["facts"] = [fact]
            with pytest.raises(Failure):
                validate(value, schema)
        value["facts"] = []
        validate(value, guided_report_schema([]))

    def test_fact_escaping_and_unbounded_list_loopholes_fail_validation(self):
        schema = guided_report_schema()
        for text in ("line\nline", 'a"b', "a\\b", "a\tb", "a\u2028b"):
            value = f.report()
            value["facts"] = [text]
            with pytest.raises(Failure):
                validate(value, schema)
        for field, (maximum, _) in ARRAY_LIMITS.items():
            value = f.report()
            value[field] = ["safe"] * (maximum + 1)
            with pytest.raises(Failure):
                validate(value, schema)
        value = f.report()
        value["issue_number"] = 2147483648
        with pytest.raises(Failure):
            validate(value, schema)

    def test_upstream_ignoring_schema_is_not_published_or_regenerated(self):
        m = self.model()
        value = f.report()
        value["summary"] = "x" * 161
        m.http.request.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]
        }
        with pytest.raises(Failure, match="LLM_INVALID_MODEL_SCHEMA"):
            m.call("analysis", {}, REPORT_SCHEMA, time.monotonic() + 30)
        assert m.http.request.call_count == 1
        m.store.finish_llm.assert_called_once()

    def test_length_finish_still_fails_even_when_content_parses(self):
        m = self.model()
        m.http.request.return_value = {
            "choices": [{"finish_reason": "length", "message": {"content": json.dumps(f.report())}}]
        }
        with pytest.raises(Failure, match="LLM_MODEL_OUTPUT_TRUNCATED"):
            m.call("analysis", {}, REPORT_SCHEMA, time.monotonic() + 30)
        assert m.http.request.call_count == 1
        m.store.finish_llm.assert_called_once()

    def test_history_is_not_reinterpreted_under_generation_limits(self):
        value = f.report()
        value["summary"] = "x" * 1000
        value["facts"] = ["Historical fact."] * 20
        validate(value, REPORT_SCHEMA)
        with pytest.raises(Failure):
            validate(value, guided_report_schema())

    def test_complete_short_report_uses_one_existing_paid_request(self):
        m = self.model()
        value = f.report()
        m.http.request.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]
        }
        assert m.call("analysis", {}, REPORT_SCHEMA, time.monotonic() + 30) == value
        assert m.http.request.call_count == 1
        m.store.reserve_llm.assert_called_once()

    def test_input_evidence_and_global_schema_are_not_shortened(self):
        m = self.model()
        data = {"evidence": {"logs": "private diagnostic " * 1000}}
        before = copy.deepcopy(data)
        body = m.payload("analysis", data, REPORT_SCHEMA)
        assert data == before
        assert "private diagnostic " * 1000 in body["messages"][1]["content"]


@patch.dict("os.environ", {"SPI_TOKEN_ACCOUNTING_MODE": "byte-bound-v1"})
class ReportCompletenessTests(unittest.TestCase):
    def test_cap_fragment_is_rejected_without_an_extra_paid_regeneration(self):
        m = Model(Mock(), "test-only", store=Mock())
        value = f.report()
        value["summary"] = "No application-level errors, pan"
        m.http.request.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]
        }
        with pytest.raises(Failure, match="LLM_INVALID_MODEL_SCHEMA"):
            m.call("analysis", {}, REPORT_SCHEMA, time.monotonic() + 30)
        assert m.http.request.call_count == 1
        m.store.finish_llm.assert_called_once()

    def test_ellipsis_or_open_parenthetical_is_not_a_complete_generated_report(self):
        from report_bounds import validate_generated_report

        for text in ("The pod itself (", "Delivery failed...", "Delivery failed"):
            value = f.report()
            value["impact"] = text
            with pytest.raises(Failure):
                validate_generated_report(value, guided_report_schema())

    def test_prompt_contains_real_headroom_not_an_invisible_schema_reference(self):
        m = Model(Mock(), "test-only", store=Mock())
        captured = {}

        def call(task, data, schema, deadline):
            captured["task"] = task
            return f.report()

        m.call = call
        m.analyze(f.event(), {"candidates": []}, {})
        assert "at most 8 words" in captured["task"]
        assert "NOT a target to fill" in captured["task"]
        assert "COMPLETE sentence" in captured["task"]


@patch.dict("os.environ", {"SPI_TOKEN_ACCOUNTING_MODE": "byte-bound-v1"})
class TrailingCitationCompletenessTests(unittest.TestCase):
    def test_complete_sentence_then_multiple_allowed_citations_is_unchanged(self):
        from report_bounds import validate_generated_report

        for key in (
            "summary",
            "match_reason",
            "impact",
            "alert_assessment",
            "hypotheses",
            "service_actions",
            "monitoring_actions",
            "missing_evidence",
        ):
            for prose in (
                "Capacity is constrained. [E001]",
                "Inspect the disk! [E001][E002]",
                "Is usage stable? [E001] [E002]",
            ):
                value = f.report()
                value[key] = [prose] if isinstance(value[key], list) else prose
                before = copy.deepcopy(value)
                assert (
                    validate_generated_report(value, guided_report_schema(), ["E001", "E002"])
                    is value
                )
                assert value == before

    def test_citation_does_not_make_fragment_or_unknown_reference_complete(self):
        from report_bounds import validate_generated_report

        for prose in (
            "Capacity is [E001]",
            "Capacity is... [E001]",
            "Capacity is... [E001][E002]",
            "Capacity is constrained. [E999]",
            "Capacity is constrained. [E001] [E999]",
            "Capacity is constrained. [E001] arbitrary-tail",
            "Capacity is constrained. [garbage]",
            "[E001]",
        ):
            value = f.report()
            value["hypotheses"] = [prose]
            with pytest.raises(Failure):
                validate_generated_report(value, guided_report_schema(), ["E001", "E002"])

    def test_absent_or_empty_allowlist_does_not_authorize_citation_stripping(self):
        from report_bounds import validate_generated_report

        for ids in (None, []):
            value = f.report()
            value["hypotheses"] = ["Capacity is constrained. [E001]"]
            with pytest.raises(Failure):
                validate_generated_report(value, guided_report_schema(), ids)

    def test_real_model_path_accepts_allowed_citations_in_one_call(self):
        m = Model(Mock(), "test-only", store=Mock())
        value = f.report()
        value["facts"] = ["Capacity is constrained [E001]."]
        value["hypotheses"] = ["Usage may rise. [E001]"]
        before = copy.deepcopy(value)
        data = {"evidence": {"artifact_context": {"index": [{"id": "E001"}]}}}
        m.http.request.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]
        }
        assert m.call("analysis", data, REPORT_SCHEMA, time.monotonic() + 30) == before
        assert m.http.request.call_count == 1
        m.store.reserve_llm.assert_called_once()

    def test_rejection_diagnostic_contains_only_fixed_field_reason_and_count(self):
        from report_bounds import validate_generated_report

        value = f.report()
        value["impact"] = "private diagnostic fragment"
        with self.assertLogs("report_bounds", level="WARNING") as logs:
            with pytest.raises(Failure):
                validate_generated_report(value, guided_report_schema())
        assert "private diagnostic" not in str(logs.output)
        assert "INCOMPLETE_SENTENCE" in str(logs.output)
