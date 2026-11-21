"""Reference prevention/validation tests; mock HTTP only, no provider calls."""

import copy
import json
import re
import time
import unittest
from unittest.mock import Mock, patch

import test_triage as f
from core import REPORT_SCHEMA, Failure
from integrations import Model


@patch.dict("os.environ", {"SPI_TOKEN_ACCOUNTING_MODE": "byte-bound-v1"})
class ReferenceContractTests(unittest.TestCase):
    """Evidence-reference contracts for the mocked analysis model."""

    def model(self):
        'Build a mocked analysis model with a mock store.'
        return Model(Mock(), "test-only", store=Mock())

    @staticmethod
    def data(ids=("E002", "E007")) -> dict[str, dict[str, dict[str, list[dict[str, str]]]]]:
        'Return evidence context indexing the given ids.'
        return {"evidence": {"artifact_context": {"index": [{"id": x} for x in ids]}}}

    def test_guided_schema_requires_an_actual_id_without_mutating_global(self) -> None:
        """Require a real evidence id and leave the global schema unchanged."""
        m = self.model()
        before = copy.deepcopy(REPORT_SCHEMA)
        body = m.payload("analysis", self.data(), REPORT_SCHEMA)
        schema = body["response_format"]["json_schema"]["schema"]
        pattern = schema["properties"]["facts"]["items"]["pattern"]
        assert re.fullmatch(pattern, "A bounded observation [E002].") is not None
        assert re.fullmatch(pattern, "A\nmultiline observation [E007].") is not None
        for text in ("An uncited observation.", "Invented reference [E003]."):
            assert re.fullmatch(pattern, text) is None
        assert before == REPORT_SCHEMA
        assert "pattern" not in REPORT_SCHEMA["properties"]["facts"]["items"]
        assert m.budget_reservation(body) > 0
        m.http.request.assert_not_called()

    def test_empty_index_requires_empty_verified_facts(self) -> None:
        """Force an empty fact list when the artifact index is empty."""
        m = self.model()
        body = m.payload("analysis", self.data(()), REPORT_SCHEMA)
        assert (
            body["response_format"]["json_schema"]["schema"]["properties"]["facts"]["maxItems"] == 0
        )
        result = f.report()
        result["facts"] = []
        m.http.request.return_value = {"choices": [{"message": {"content": json.dumps(result)}}]}
        assert m.call("analysis", self.data(()), REPORT_SCHEMA, time.monotonic() + 20) == result

    def test_invalid_reference_fails_after_one_repair_and_logs_counts_not_content(self) -> None:
        """Log the invalid-reference count and omit the private fact text."""
        m = self.model()
        result = f.report()
        result["facts"] = ["PRIVATE-FACT-TEXT [E002] and [E999]"]
        m.http.request.return_value = {"choices": [{"message": {"content": json.dumps(result)}}]}
        with self.assertLogs("integrations", level="WARNING") as logs:
            with self.assertRaises(Failure) as caught:
                m.call("analysis", self.data(), REPORT_SCHEMA, time.monotonic() + 20)
        assert caught.exception.code == "LLM_INVALID_EVIDENCE_REFERENCE"
        # Invalid evidence references trigger one retry, so the model is called twice.
        expected_model_calls = 2
        assert m.http.request.call_count == expected_model_calls
        text = "\n".join(logs.output)
        assert "unknown_reference_count" in text
        assert "PRIVATE-FACT-TEXT" not in text
        assert "E999" not in text

    def test_unsupported_artifact_identity_fails_before_any_paid_call(self) -> None:
        """Reject an illegal artifact id before HTTP or budget reservation."""
        m = self.model()
        with self.assertRaisesRegex(Failure, "LLM_INVALID_EVIDENCE_CONTEXT"):
            m.call("analysis", self.data(("E001|.*",)), REPORT_SCHEMA, time.monotonic() + 20)
        m.http.request.assert_not_called()
        m.store.reserve_llm.assert_not_called()

    def test_analysis_instructions_use_real_ids_not_a_fictional_example(self) -> None:
        """Put the real artifact ids, not a fictional example, in the task."""
        m = self.model()
        captured = {}

        def call(task, data, schema, deadline) -> object:
            captured["task"] = task
            return f.report()

        m.call = call
        evidence = {"bundle": {"model_context": self.data()["evidence"]["artifact_context"]}}
        m.analyze(f.event(), {"candidates": []}, evidence)
        assert "E002" in captured["task"]
        assert "E007" in captured["task"]
        assert "[E003]" not in captured["task"]
        assert "facts=[]" in captured["task"]


if __name__ == "__main__":
    unittest.main()
