"""Human evidence navigation and snapshots, no live observability or inference."""

import json
import os
import stat
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import graph_evidence as graphs
import pytest
import test_graph_evidence as fixture
from evidence_bundle import (
    grafana_panel_url,
    navigation_markdown,
    prepare_bundle,
    storage_markdown,
    storage_objects,
)
from graph_contract import GraphError
from telemetry import TelemetryCollector, grafana_explore_url
from test_triage import event


class NavigationTests(unittest.TestCase):
    def test_s3_path_publishes_collected_explore_links_and_explicit_gaps(self):
        url = grafana_explore_url(
            "https://grafana.socrat.alchemmist.xyz", "loki", '{namespace="api"}', 100, 200, "expr"
        )
        b = prepare_bundle(
            event(),
            {"missing": [{"source": "graphs", "reason": "GRAPH_CAPTURE_FAILED"}]},
            [
                {
                    "name": "logs.json",
                    "content": {"response": {"status": "success", "data": {"result": []}}},
                }
            ],
            [{"title": "Loki logs", "url": url}],
        )
        text = storage_markdown(storage_objects(b))
        assert url in text
        assert "GRAPH_CAPTURE_FAILED" in text
        assert "logs.json" in text
        assert "sign" in text.lower()
        panes = json.loads(parse_qs(urlsplit(url).query)["panes"][0])
        assert panes["spi"]["range"] == {"from": "100000", "to": "200000"}

    def test_navigation_rejects_external_origin_userinfo_fragment_and_host_suffix(self):
        for url in (
            "https://evil.example/explore?x=1",
            "https://grafana.socrat.alchemmist.xyz.evil/explore?x=1",
            "https://user@grafana.socrat.alchemmist.xyz/explore?x=1",
            "https://grafana.socrat.alchemmist.xyz/explore?x=1#bad",
            "https://grafana.socrat.alchemmist.xyz/explore?x=1) [bad](https://evil.example)",
            "https://grafana.socrat.alchemmist.xyz/explore?x=1\nbad",
        ):
            assert "](" + url + ")" not in navigation_markdown(
                {"links": [{"title": "bad", "url": url}]}
            )

    def test_panel_url_keeps_absolute_png_range_and_variables(self):
        source = {
            "dashboard_uid": "api-panel",
            "panel_id": 12,
            "variables": {"namespace": "api", "node": "a b"},
            "from_ms": 100000,
            "to_ms": 200000,
        }
        q = parse_qs(urlsplit(grafana_panel_url(source)).query)
        assert q["from"] == ["100000"]
        assert q["to"] == ["200000"]
        assert q["viewPanel"] == ["12"]
        assert q["var-node"] == ["a b"]
        assert q["forceLogin"] == ["true"]

    def test_oversize_json_is_a_valid_explicit_envelope_not_chopped_json(self):
        b = prepare_bundle(
            event(), {}, [{"name": "logs.json", "content": {"lines": ["x" * 10000] * 30}}]
        )
        for key, raw in storage_objects(b):
            assert json.loads(raw) is not None
        assert b["manifest"]["artifacts"][0]["truncated"]
        value = json.loads(storage_objects(b)[1][1])
        assert value["representation"] == "bounded_json_excerpt"
        assert "sanitized_sha256" in value

    def test_fair_budget_keeps_later_logs_parseable_and_redacts_response(self):
        rows = [
            {
                "name": "logs-" + str(i) + ".json",
                "content": {"password": "private-value", "lines": ["x" * 90000]},
            }
            for i in range(12)
        ]
        b = prepare_bundle(event(), {}, rows)
        objects = storage_objects(b)
        assert len(b["manifest"]["artifacts"]) == 12
        for key, raw in objects:
            json.loads(raw)
            assert b"private-value" not in raw
        assert sum(r["stored_chars"] for r in b["manifest"]["artifacts"]) <= 360000


class PrivateSpoolTests(unittest.TestCase):
    setUp = fixture.GraphEvidenceTests.setUp

    def test_fsgroup_modes_are_tightened_without_re_render_or_content_change(self):
        captured, _ = graphs.collect(self.event, self.client)
        ref = captured[0]["reference"]
        root = graphs.ARTIFACT_ROOT
        d = root / ref["event_key"]
        png = d / (ref["render_digest"] + ".png")
        os.chmod(root, 0o2770)
        os.chmod(d, 0o2770)
        os.chmod(d / "capture.json", 0o660)
        os.chmod(png, 0o660)
        again, missing = graphs.collect(self.event, self.client)
        assert not missing
        assert again == captured
        assert self.client.render.call_count == 1
        assert graphs.read_artifact(ref) == self.raw
        for path in (root, d, d / "capture.json", png):
            assert stat.S_IMODE(path.stat().st_mode) & 63 == 0

    def test_world_access_is_rejected_not_silently_repaired(self):
        root = graphs.ARTIFACT_ROOT
        root.mkdir()
        os.chmod(root, 0o777)
        with pytest.raises(GraphError):
            graphs.collect(self.event, self.client)
        assert stat.S_IMODE(root.stat().st_mode) == 511
        self.client.render.assert_not_called()

    def test_foreign_group_access_is_rejected(self):
        root = graphs.ARTIFACT_ROOT
        root.mkdir()
        os.chmod(root, 0o770)
        with patch.object(graphs.os, "getegid", return_value=os.getegid() + 1):
            with pytest.raises(GraphError):
                graphs.collect(self.event, self.client)
        assert stat.S_IMODE(root.stat().st_mode) == 504

    def test_png_and_dashboard_links_use_the_same_captured_window(self):
        captured, missing = graphs.collect(self.event, self.client)
        b = graphs.attach(prepare_bundle(self.event, {}, []), captured, missing)
        text = storage_markdown(storage_objects(b))
        assert "Open Grafana panel" in text
        assert "(PNG)" in text
        assert str(captured[0]["source"]["from_ms"]) in text
        assert str(captured[0]["source"]["to_ms"]) in text

    def test_failed_render_keeps_a_panel_link_and_visible_failure(self):
        self.client.render.side_effect = GraphError("RENDER_TIMEOUT")
        captured, missing = graphs.collect(self.event, self.client)
        assert not captured
        b = graphs.attach(prepare_bundle(self.event, {}, []), captured, missing)
        text = storage_markdown(storage_objects(b))
        assert "capture unavailable" in text
        assert "RENDER_TIMEOUT" in text
        assert "/d/" in text


class SnapshotTests(unittest.TestCase):
    def collect(self, labels=None, fail=False):
        e = event(start="2026-11-11T09:00:00Z")
        e["labels"] = labels or {
            "alertname": "Test",
            "namespace": "api",
            "pod": "api-123",
            "container": "api",
        }
        h = Mock()
        if fail:
            from core import Failure

            h.request.side_effect = Failure("UPSTREAM_TIMEOUT")
        else:
            h.request.return_value = {
                "status": "success",
                "data": {"resultType": "streams", "result": []},
            }
        with patch("telemetry.time.time", return_value=1794388200):
            result = TelemetryCollector(h, "http://grafana.internal", "test-only").collect(e, {})
        return result, h

    def test_baseline_snapshot_exists_without_error_anchor_or_matching_lines(self):
        r, h = self.collect()
        rows = [a for a in r["artifacts"] if "baseline-logs" in a["name"]]
        assert len(rows) == 1
        c = rows[0]["content"]
        assert c["response"]["status"] == "success"
        assert c["stored_lines"] == 0
        assert "error|exception" not in c["query"]
        assert h.request.call_count <= 10

    def test_failed_read_is_a_receipt_not_an_empty_successful_snapshot(self):
        r, h = self.collect(fail=True)
        rows = [a for a in r["artifacts"] if "receipt" in a["name"]]
        assert rows
        assert rows[0]["content"]["status"] == "failed"
        assert "response" not in rows[0]["content"]

    def test_unverified_scrape_exporter_is_not_used_as_affected_pod(self):
        r, h = self.collect(
            {
                "alertname": "Test",
                "namespace": "cattle-system",
                "pod": "kube-state-metrics-abcd",
                "container": "kube-state-metrics",
            }
        )
        assert any(x["reason"] == "EXPORTER_POD_NOT_VERIFIED" for x in r["missing"])
        assert not any("/loki/" in c.args[1] for c in h.request.call_args_list)

    def test_invalid_pod_does_not_widen_to_namespace_only(self):
        r, h = self.collect(
            {"alertname": "Test", "namespace": "api", "pod": "invalid pod!", "container": "api"}
        )
        assert any(x["reason"] == "UNSAFE_LABEL" for x in r["missing"])
        assert not any("/loki/" in c.args[1] for c in h.request.call_args_list)
