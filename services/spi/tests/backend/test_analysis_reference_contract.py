"""Reference prevention/validation tests; mock HTTP only, no provider calls."""

import copy
import json
import re
import time
import unittest
from unittest.mock import Mock, patch

import pytest
import test_triage as f
from core import REPORT_SCHEMA, Failure
from integrations import Model


@patch.dict("os.environ", {"SPI_TOKEN_ACCOUNTING_MODE": "byte-bound-v1"})
class ReferenceContractTests(unittest.TestCase):
    def model(self):
        return Model(Mock(), "test-only", store=Mock())

    @staticmethod
    def data(ids=("E002", "E007")):
        return {"evidence": {"artifact_context": {"index": [{"id": x} for x in ids]}}}

    def test_guided_schema_requires_an_actual_id_without_mutating_global(self):
        m = self.model()
        before = copy.deepcopy(REPORT_SCHEMA)
        body = m.payload("analysis", self.data(), REPORT_SCHEMA)
        schema = body["response_format"]["json_schema"]["schema"]
        pattern = schema["properties"]["facts"]["items"]["pattern"]
        assert re.fullmatch(pattern, "A bounded observation [E002].") is not None
        # Generation is now single-line bounded ASCII to avoid mandatory
        # JSON escaping. Citation support itself remains unchanged.
        assert re.fullmatch(pattern, "A\nmultiline observation [E007].") is None
        assert re.fullmatch(pattern, "A single-line observation [E007].") is not None
        for text in ("An uncited observation.", "Invented reference [E003]."):
            assert re.fullmatch(pattern, text) is None
        assert REPORT_SCHEMA == before
        assert "pattern" not in REPORT_SCHEMA["properties"]["facts"]["items"]
        assert m.budget_reservation(body) > 0
        m.http.request.assert_not_called()

    def test_empty_index_requires_empty_verified_facts(self):
        m = self.model()
        body = m.payload("analysis", self.data(()), REPORT_SCHEMA)
        assert (
            body["response_format"]["json_schema"]["schema"]["properties"]["facts"]["maxItems"] == 0
        )
        result = f.report()
        result["facts"] = []
        m.http.request.return_value = {"choices": [{"message": {"content": json.dumps(result)}}]}
        assert m.call("analysis", self.data(()), REPORT_SCHEMA, time.monotonic() + 20) == result

    def test_invalid_reference_fails_after_one_repair_and_logs_counts_not_content(self):
        m = self.model()
        result = f.report()
        result["facts"] = ["PRIVATE-FACT-TEXT [E002] and [E999]"]
        m.http.request.return_value = {"choices": [{"message": {"content": json.dumps(result)}}]}
        with self.assertLogs("integrations", level="WARNING") as logs:
            with pytest.raises(Failure) as caught:
                m.call("analysis", self.data(), REPORT_SCHEMA, time.monotonic() + 20)
        assert caught.value.code == "LLM_INVALID_EVIDENCE_REFERENCE"
        assert m.http.request.call_count == 2
        text = "\n".join(logs.output)
        assert "unknown_reference_count" in text
        assert "PRIVATE-FACT-TEXT" not in text
        assert "E999" not in text

    def test_unsupported_artifact_identity_fails_before_any_paid_call(self):
        m = self.model()
        with pytest.raises(Failure, match="LLM_INVALID_EVIDENCE_CONTEXT"):
            m.call("analysis", self.data(("E001|.*",)), REPORT_SCHEMA, time.monotonic() + 20)
        m.http.request.assert_not_called()
        m.store.reserve_llm.assert_not_called()

    def test_analysis_instructions_use_real_ids_not_a_fictional_example(self):
        m = self.model()
        captured = {}

        def call(task, data, schema, deadline):
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
