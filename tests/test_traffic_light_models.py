"""Owner capture and narrow TV addition regression."""

import copy
import json
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "scripts/build-traffic-light-models.py"))

LLM_ACTIVITY_PANEL_ID = 938
RETIRED_EMBEDDING_PANEL_ID = 937
RETIRED_AI_COMPACT_PANEL_ID = 930


class Models(unittest.TestCase):
    """Tests for Models."""
    def setUp(self):
        self.d = json.loads(
            (ROOT / "charts/monitoring-k3s/dashboards/traffic-light.json").read_text()
        )

    def test_idempotent_and_owner_exact(self):
        assert M["build"](self.d) == self.d
        for p in self.d["panels"]:
            if p["id"] == LLM_ACTIVITY_PANEL_ID:
                assert not p["options"]["legend"]["showLegend"]
                assert not p["title"]
                assert not p.get("description")
                assert "timeFrom" not in p
                assert "[1m]" in p["targets"][0]["expr"]
                assert p["fieldConfig"]["defaults"]["color"]["mode"] == "palette-classic-by-name"
        assert RETIRED_EMBEDDING_PANEL_ID not in {p["id"] for p in self.d["panels"]}
        assert (
            "sum by (requested_model)"
            in next(p for p in self.d["panels"] if p["id"] == LLM_ACTIVITY_PANEL_ID)["targets"][0][
                "expr"
            ]
        )
        assert RETIRED_AI_COMPACT_PANEL_ID not in {p["id"] for p in self.d["panels"]}

    def test_overlap_rejected(self):
        d = copy.deepcopy(self.d)
        next(p for p in d["panels"] if p["id"] == LLM_ACTIVITY_PANEL_ID)["gridPos"]["y"] = 10
        with self.assertRaises(ValueError):
            M["build"](d)

    def test_bottom_rejected(self):
        d = copy.deepcopy(self.d)
        next(p for p in d["panels"] if p["id"] == LLM_ACTIVITY_PANEL_ID)["gridPos"]["h"] = 7
        with self.assertRaises(ValueError):
            M["build"](d)


class SplitCascade(unittest.TestCase):
    """Tests for SplitCascade."""
    def test_split_preserves_query_semantics_and_boundary(self):
        d = json.loads((ROOT / "charts/monitoring-k3s/dashboards/traffic-light.json").read_text())
        p = {p["id"]: p for p in d["panels"]}
        for pid, x, name in [(936, 2, "Cascade age"), (939, 0, "Samples/s")]:
            assert p[pid]["gridPos"] == dict(x=x, y=12, w=2, h=2)
            assert len(p[pid]["targets"]) == 1
            assert p[pid]["targets"][0]["legendFormat"] == name
            assert p[pid]["fieldConfig"]["defaults"]["color"]["fixedColor"] == "#E0B860"
            assert "or vector(-2)" in p[pid]["targets"][0]["expr"]
        assert p[938]["gridPos"] == dict(x=16, y=14, w=8, h=5)
        assert (
            p[938]["gridPos"]["y"] + p[938]["gridPos"]["h"]
            == p[909]["gridPos"]["y"] + p[909]["gridPos"]["h"]
        )
        assert "todo_downsample_blocks" not in json.dumps(d)
        assert "thanos_compact_halted" not in json.dumps(d)
