"""Tests for traffic light quality gating."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "quality", ROOT / "scripts/build-traffic-light-quality.py"
)
Q = importlib.util.module_from_spec(SPEC)

# Dashboard panel ids owned by the quality column.
AI_BLOCK_PANEL_ID = 930
STORAGE_TRAFFIC_PANEL_ID = 931
REGISTRY_TRAFFIC_PANEL_ID = 932
REMOVED_SERVICE_PANEL_ID = 933
PG_REPLICA_PANEL_ID = 934
AI_BLOCK_TARGET_COUNT = 2
SERVICE_TRAFFIC_WIDTH = 4
SPEC.loader.exec_module(Q)


class QualityPanelsTest(unittest.TestCase):
    """Tests for QualityPanelsTest."""
    def setUp(self):
        self.d = json.loads(Q.SOURCE.read_text())
        self.p = {p["id"]: p for p in self.d["panels"]}

    def test_generator_idempotent_and_preserves_every_unrelated_panel(self):
        assert Q.build(self.d) == self.d
        base = copy.deepcopy(self.d)
        base["panels"] = [p for p in base["panels"] if p["id"] not in Q.IDS]
        built = Q.build(base)
        assert [p for p in built["panels"] if p["id"] not in Q.IDS] == base["panels"]
        assert {k: v for k, v in built.items() if k != "panels"} == {
            k: v for k, v in base.items() if k != "panels"
        }

    def test_writer_preserves_existing_format_and_is_stable(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "dashboard.json"
            with patch.object(Q, "SOURCE", path):
                Q.write(self.d)
                first = path.read_bytes()
                Q.write(Q.build(json.loads(first)))
                assert path.read_bytes() == first
            for p in self.d["panels"]:
                if p["id"] not in Q.IDS:
                    formatted = "\n".join(
                        "    " + line
                        for line in json.dumps(p, ensure_ascii=False, indent=2).splitlines()
                    )
                    assert formatted in first.decode()

    def test_preserves_future_manual_network_geometry(self):
        panel = next(p for p in self.d["panels"] if p["id"] == STORAGE_TRAFFIC_PANEL_ID)
        panel["gridPos"] = {"x": 12, "y": 13, "w": 3, "h": 3}
        built = Q.build(self.d)
        assert (
            next(p for p in built["panels"] if p["id"] == STORAGE_TRAFFIC_PANEL_ID)["gridPos"]
            == panel["gridPos"]
        )

    def test_manual_return_to_legacy_width_is_also_authoritative(self):
        grids = {931: {"x": 12, "y": 10, "w": 4, "h": 3}, 932: {"x": 12, "y": 13, "w": 4, "h": 3}}
        for p in self.d["panels"]:
            if p["id"] in grids:
                p["gridPos"] = grids[p["id"]]
        built = Q.build(self.d)
        for p in built["panels"]:
            if p["id"] in grids:
                assert p["gridPos"] == grids[p["id"]]

    def test_will_not_move_owner_panels_to_force_space(self):
        self.d["panels"][0]["gridPos"] = {"x": 12, "y": 14, "w": 4, "h": 4}
        with self.assertRaises(ValueError):
            Q.build(self.d)

    def test_backup_latest_state_not_last_known_good(self):
        for i in [934, 935]:
            p = self.p[i]
            assert p["options"]["reduceOptions"]["calcs"] == ["last"]
            e = p["targets"][0]["expr"]
            for token in ["or vector(-2)", "timestamp("]:
                assert token in e
            assert "or vector(0)" not in e

    def test_native_network_not_fabricated_object_or_image_counts(self):
        for i in [931, 932]:
            p = self.p[i]
            e = p["targets"][0]["expr"]
            assert p["type"] == "stat"
            for token in [
                "container_network_receive_bytes_total",
                "container_network_transmit_bytes_total",
                "[5m]",
                "timestamp(",
                "kube_pod_info",
                "2*count(",
                "metrics/cadvisor",
                "label_join(",
            ]:
                assert token in e
            assert "or vector(0)" not in e
            assert p["options"]["reduceOptions"]["calcs"] == ["last"]
            assert "or on(direction)" in e
            assert "vector(-2)" in e
            assert p["hideTimeOverride"]
            assert "NOT object or OCI counts" in p["description"]

    def test_one_compact_ai_block_replaces_http_errors(self):
        assert AI_BLOCK_PANEL_ID not in self.p  # Owner removed this TV block.
        p = Q.ai_quality()
        assert p["type"] == "stat"
        assert p["options"]["graphMode"] == "none"
        assert len(p["targets"]) == AI_BLOCK_TARGET_COUNT
        queue, latency = [t["expr"] for t in p["targets"]]
        assert "num_requests_waiting" in queue
        for token in ["histogram_quantile(0.95", "[15m]", ">=20", "vector(-1)", "< +Inf"]:
            assert token in latency
        for expr in [queue, latency]:
            assert "timestamp(" in expr
            assert "up{" in expr
            assert "or vector(-2)" in expr
            assert "or vector(0)" not in expr
        assert p["fieldConfig"]["overrides"][0]["properties"][0]["value"] == "s"
        assert "traefik_service_requests_total" not in json.dumps(p)

    def test_no_new_blue_and_no_ai_dominance(self):
        for i in Q.IDS & self.p.keys():
            p = self.p[i]
            assert "#5794F2" not in json.dumps(p)
            if i != AI_BLOCK_PANEL_ID:
                assert "vllm:" not in json.dumps(p)
        assert (
            self.p[STORAGE_TRAFFIC_PANEL_ID]["fieldConfig"]["defaults"]["color"]["fixedColor"]
            == "#B877D9"
        )
        assert (
            self.p[REGISTRY_TRAFFIC_PANEL_ID]["fieldConfig"]["defaults"]["color"]["fixedColor"]
            == "#2EBFA5"
        )

    def test_more_service_room_without_moving_originals(self):
        assert REMOVED_SERVICE_PANEL_ID not in self.p
        for i in [931, 932]:
            assert self.p[i]["gridPos"]["w"] == SERVICE_TRAFFIC_WIDTH
            assert self.p[i]["options"]["graphMode"] == "area"
        assert "socrat:node_pressure" not in json.dumps([self.p[i] for i in Q.IDS & self.p.keys()])

    def test_cascade_split_cards_without_new_css(self):
        for i, x, y in [(934, 4, 12), (935, 6, 14)]:
            assert self.p[i]["gridPos"] == {"x": x, "y": y, "w": 2, "h": 2}
        for i, x in [(936, 2), (939, 0)]:
            p = self.p[i]
            assert p["gridPos"] == {"x": x, "y": 12, "w": 2, "h": 2}
            assert len(p["targets"]) == 1
            t = p["targets"][0]
            assert t["instant"]
            for token in ["or vector(-2)", "timestamp(", "up{"]:
                assert token in t["expr"]
        assert "thanos-cascade" in self.p[936]["targets"][0]["expr"]
        assert "head_samples_appended_total" in self.p[939]["targets"][0]["expr"]

    def test_backup_success_not_restore_claim(self):
        for i in [934, 935]:
            p = self.p[i]

            e = p["targets"][0]["expr"]
            if i == PG_REPLICA_PANEL_ID:
                assert "cnpg_pg_replication_streaming_replicas" in e
                assert "lms-database-backup" not in e
                continue
            assert "NOT proof" in p["description"]
            assert "last_successful_time" in e
            assert "vector(-3)" in e
            assert "vector(-1)" in e
            assert p["options"]["graphMode"] == "none"
