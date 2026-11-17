"""Offline metadata contract; never provisions alerts or creates notifications."""

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExecutionLinks(unittest.TestCase):
    def test_id_is_annotation_not_alert_instance_or_threshold_input(self):
        definition = json.loads((ROOT / "docs/n8n/spi/alerts.json").read_text())
        rule = next(r for r in definition["rules"] if r["uid"] == "spi-triage-failures")
        by_id = {q["refId"]: q for q in rule["data"]}
        assert rule["condition"] == "C"
        assert by_id["C"]["model"]["expression"] == "A"
        expected_expr = (
            'sum(count_over_time({k8s_namespace_name="automation"}'
            ' |= "spi-triage" | json | event=~"stage_failed|handoff_failed" [20m]))'
            " or vector(0)"
        )
        assert by_id["A"]["model"]["expr"] == expected_expr
        assert rule["for"] == "2m"
        assert "n8n_execution_id" not in rule["labels"]
        query = by_id["B"]["model"]["expr"]
        assert query.startswith("max(max_over_time(")
        assert "unwrap n8n_execution_id" in query
        assert '__error__="" [20m]' in query
        assert query.endswith("or vector(0)")
        template = rule["annotations"]["n8n_url"]
        assert "if gt $values.B.Value 0.0" in template
        assert "/workflow/J9akzlydrf9XZiID/executions/" in template
        assert "16473" not in template  # no hard-coded historical execution

    def test_native_workflow_accepts_all_current_safe_deferred_codes(self):
        workflow = json.loads((ROOT / "docs/n8n/spi/triage-workflow.json").read_text())
        code = next(
            n["parameters"]["jsCode"]
            for n in workflow["nodes"]
            if n["name"] == "Select Claimed Job"
        )
        match = re.search(r"if\(x.status==='deferred' && !(\[[^\n]+?\])\.includes\(x.code\)", code)
        assert match is not None
        assert set(ast.literal_eval(match[1])) == {
            "LLM_ADMISSION_DEFERRED",
            "WORKER_ADMISSION_DEFERRED",
            "GRAPH_CAPTURE_DEFERRED",
            "GITHUB_READ_TIMEOUT",
            "GITHUB_READ_NETWORK_ERROR",
            "MATCH_PROGRESS_DEFERRED",
            "STORAGE_TRANSIENT",
        }
        # Existing production contract admits storage retries ONLY in Publish.
        storage_retry_guard = (
            "if(x.status==='deferred' && x.code==='STORAGE_TRANSIENT'"
            " && x.stage!=='publish') throw new Error('INVALID_SPI_WAIT_CODE');"
        )
        assert storage_retry_guard in code
