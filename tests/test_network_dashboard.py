"""Contracts for a Grafana-only network overview; no synthetic mesh health."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "charts/monitoring-k3s/dashboards/network.json"


def _mapping(value: object) -> dict[str, object]:
    """Validate each JSON key without inventing types for unknown nested fields."""
    assert isinstance(value, dict)
    result: dict[str, object] = {}
    for key, item in value.items():
        assert isinstance(key, str)
        result[key] = item
    return result


def _list(value: object) -> list[object]:
    """Accept only a real JSON array before indexing into it."""
    assert isinstance(value, list)
    return value


def dashboard() -> dict[str, object]:
    value: object = json.loads(PATH.read_text())
    return _mapping(value)


def test_native_panels_and_existing_datasource_only() -> None:
    """Require unique native panels and the existing Prometheus datasource."""
    d = dashboard()
    panels = [_mapping(p) for p in _list(d["panels"])]
    assert d["uid"] == "socrat-network"
    assert d["refresh"] == "30s"
    assert len({p["id"] for p in panels}) == len(panels)
    for p in panels:
        assert p["type"] in {"text", "stat", "table", "timeseries", "nodeGraph"}
        for target in _list(p.get("targets", [])):
            t = _mapping(target)
            assert t["datasource"] == {"type": "prometheus", "uid": "prometheus"}
            expr = t["expr"]
            assert isinstance(expr, str)
            assert "vector(" not in expr  # No fabricated discovery or healthy fallback.


def test_graphs_have_native_edge_schema_and_instant_tables() -> None:
    """Require both node graphs to expose instant edge tables."""
    dashboard_doc = dashboard()
    graphs = [
        _mapping(p) for p in _list(dashboard_doc["panels"]) if _mapping(p)["type"] == "nodeGraph"
    ]
    assert len(graphs) == 2
    for p in graphs:
        t = _mapping(_list(p["targets"])[0])
        assert t["refId"] == "edges"
        assert bool(t["instant"]) and not bool(t["range"]) and t["format"] == "table"
        include = _mapping(_mapping(_mapping(_list(p["transformations"])[0])["options"])["include"])
        names = _list(include["names"])
        assert {"id", "source", "target", "Value"} <= set(names)
        rename = _mapping(
            _mapping(_mapping(_list(p["transformations"])[1])["options"])["renameByName"]
        )
        assert rename["Value"] == "mainstat"
        expr = t["expr"]
        assert isinstance(expr, str)
        assert "timestamp(" in expr and "< 120" in expr


def test_probe_color_requires_real_fresh_success_or_failure() -> None:
    """Require probe color to reflect fresh real success or failure."""
    doc = dashboard()
    p = _mapping(next(page for page in _list(doc["panels"]) if _mapping(page)["id"] == 4))
    q = _mapping(_list(p["targets"])[0])["expr"]
    assert isinstance(q, str)
    assert "probe_success" in q and 'job="service-probes"' in q
    assert "== 1" in q and "== 0" in q
    assert "#73BF69" in q and "#F2495C" in q
    assert "detail__observer" in q and "detail__endpoint" in q
    assert "${probe_group:regex}" in q


def test_placement_is_not_colored_as_connectivity() -> None:
    """Keep pod placement distinct from connectivity coloring."""
    doc = dashboard()
    p = _mapping(next(page for page in _list(doc["panels"]) if _mapping(page)["id"] == 5))
    q = _mapping(_list(p["targets"])[0])["expr"]
    assert isinstance(q, str)
    assert "kube_pod_info" in q and "kube_pod_status_phase" in q
    assert 'phase="Running"' in q
    assert "color" not in q and "probe_success" not in q
    assert "${namespace:regex}" in q
    description = p["description"]
    assert isinstance(description, str)
    assert "not imply network health" in description


def test_scope_and_unknown_state_are_explicit() -> None:
    """State that missing data is not discovery or recovery."""
    doc = dashboard()
    text_panel = _mapping(
        next(page for page in _list(doc["panels"]) if _mapping(page)["type"] == "text")
    )
    text = _mapping(text_panel["options"])["content"]
    assert isinstance(text, str)
    assert "не обнаруживает" in text
    assert "No data" in text and "не восстановление" in text
    assert "одного cluster-prober" in text
    assert "Ready ≠" in text


def test_dashboard_uses_existing_provisioning_owner() -> None:
    """Bind the overview to the existing Grafana provisioning template."""
    template = (ROOT / "charts/monitoring-k3s/templates/socrat-dashboard.yaml").read_text()
    assert '"network"' in template
    assert 'grafana_dashboard: "1"' in template
