"""Short time pickers must not shrink increase below the scrape interval."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

TABLE_PANEL_ID = 4
REQUEST_TARGET_COUNT = 5
DASHBOARD_PANEL_COUNT = 4
TABLE_GRID_Y = 16
REQUEST_PANEL_HEIGHT = 8
REQUEST_MODELS = ("qwen3.8-27b", "venice-agentic-deepseek-v4.1-flash-uncensored", "o-deepseek")


@pytest.mark.parametrize("panel_id", [1, 2, 3])
def test_requests_window_is_independent_of_time_picker(panel_id: int) -> None:
    """Both model panels retain every original fixed-window and missing-data guard."""
    d = json.loads(
        (
            Path(__file__).resolve().parents[1] / "charts/monitoring-k3s/dashboards/llm-keys.json"
        ).read_text()
    )
    p = next(p for p in d["panels"] if p["id"] == panel_id)
    expr = p["targets"][0]["expr"]
    assert "increase(" in expr
    assert "[1m]" in expr
    assert "$__interval" not in expr
    assert "or vector(0)" not in expr
    assert p["fieldConfig"]["defaults"]["custom"]["spanNulls"] is False
    assert p["fieldConfig"]["defaults"]["custom"]["axisLabel"] == "requests / rolling minute"
    assert "must not be summed" in p["description"]
    table = next(p for p in d["panels"] if p["id"] == TABLE_PANEL_ID)
    assert all("[30d]" in t["expr"] for t in table["targets"])


def test_temporary_acceptance_keys_are_not_user_activity() -> None:
    """Temporary acceptance keys stay excluded from every dashboard query."""
    d = json.loads(
        (
            Path(__file__).resolve().parents[1] / "charts/monitoring-k3s/dashboards/llm-keys.json"
        ).read_text()
    )
    targets = [t for p in d["panels"] for t in p.get("targets", [])]
    assert len(targets) == REQUEST_TARGET_COUNT
    assert all('api_key_alias!~"venice-acceptance-.*"' in t["expr"] for t in targets)


def test_models_are_separate_and_public_content_is_aggregate() -> None:
    """Retain upstream model separation, public annotation and layout contracts."""
    d = json.loads(
        (
            Path(__file__).resolve().parents[1] / "charts/monitoring-k3s/dashboards/llm-keys.json"
        ).read_text()
    )
    assert len(d["panels"]) == DASHBOARD_PANEL_COUNT
    assert [p["id"] for p in d["panels"]] == [1, 2, 3, TABLE_PANEL_ID]
    assert d["annotations"] == {"list": []}
    assert d["time"]["from"] == "now-1h"
    for panel, model in zip(d["panels"][:3], REQUEST_MODELS, strict=True):
        expr = panel["targets"][0]["expr"]
        label = "requested_model" if model == "o-deepseek" else "model"
        assert label + '="' + model + '"' in expr
        assert "sum by (api_key_alias)" in expr
        assert "[1m]" in expr
        assert "$__interval" not in expr
    assert d["panels"][3]["gridPos"]["y"] == TABLE_GRID_Y
    assert all(p["gridPos"]["h"] == REQUEST_PANEL_HEIGHT for p in d["panels"][:3])


@pytest.mark.parametrize("violation", ["zero-fill", "span-nulls", "picker-window", "wrong-model"])
def test_second_model_rejects_semantic_regressions(violation: str) -> None:
    """Reject model/query/absence regressions on synthetic JSON, without any client."""
    d = json.loads(
        (
            Path(__file__).resolve().parents[1] / "charts/monitoring-k3s/dashboards/llm-keys.json"
        ).read_text()
    )
    panel = d["panels"][1]
    if violation == "zero-fill":
        panel["targets"][0]["expr"] += " or vector(0)"
    elif violation == "span-nulls":
        panel["fieldConfig"]["defaults"]["custom"]["spanNulls"] = True
    elif violation == "picker-window":
        panel["targets"][0]["expr"] = panel["targets"][0]["expr"].replace("[1m]", "[$__interval]")
    else:
        panel["targets"][0]["expr"] = panel["targets"][0]["expr"].replace(
            REQUEST_MODELS[1], REQUEST_MODELS[0]
        )
    with patch.object(Path, "read_text", return_value=json.dumps(d)):
        if violation == "wrong-model":
            with pytest.raises(AssertionError):
                test_models_are_separate_and_public_content_is_aggregate()
        else:
            with pytest.raises(AssertionError):
                test_requests_window_is_independent_of_time_picker(2)


def test_chart_titles_use_litellm_route_names() -> None:
    """Keep exact owner-selected route titles without changing query model matchers."""
    d = json.loads(
        (
            Path(__file__).resolve().parents[1] / "charts/monitoring-k3s/dashboards/llm-keys.json"
        ).read_text()
    )
    assert [p["title"] for p in d["panels"][:3]] == [
        "Requests by API key — qwen3.8-27b",
        "Requests by API key — v-deepseek-uc",
        "Requests by API key — o-deepseek",
    ]


def test_key_colors_are_stable_across_model_charts() -> None:
    """Use the shared alias legend and name-based palette without per-panel overrides."""
    d = json.loads(
        (
            Path(__file__).resolve().parents[1] / "charts/monitoring-k3s/dashboards/llm-keys.json"
        ).read_text()
    )
    for panel in d["panels"][:3]:
        assert panel["fieldConfig"]["defaults"]["color"]["mode"] == "palette-classic-by-name"
        assert panel["targets"][0]["legendFormat"] == "{{api_key_alias}}"
        assert panel["fieldConfig"]["overrides"] == []


def test_owner_three_chart_grid_and_legend() -> None:
    """Retain incoming exact two-column grid and all three bottom legends."""
    d = json.loads(
        (
            Path(__file__).resolve().parents[1] / "charts/monitoring-k3s/dashboards/llm-keys.json"
        ).read_text()
    )
    assert [p["gridPos"] for p in d["panels"]] == [
        dict(x=x, y=y, w=w, h=8) for x, y, w in [(0, 0, 12), (12, 0, 12), (0, 8, 12), (0, 16, 24)]
    ]
    assert all(p["options"]["legend"]["placement"] == "bottom" for p in d["panels"][:3])
