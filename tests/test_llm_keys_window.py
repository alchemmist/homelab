"""Short time pickers must not shrink increase below the scrape interval."""

import json
from pathlib import Path

TABLE_PANEL_ID = 4
REQUEST_TARGET_COUNT = 3


def test_requests_window_is_independent_of_time_picker() -> None:
    """The requests panel uses a fixed one-minute increase, not the picker interval."""
    d = json.loads(
        (
            Path(__file__).resolve().parents[1] / "charts/monitoring-k3s/dashboards/llm-keys.json"
        ).read_text()
    )
    p = next(p for p in d["panels"] if p["id"] == 1)
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
