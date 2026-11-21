"""Render app-owned public access, without an aggregate chart/Application."""

import subprocess
from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHARTS = {
    "grafana": "deploy/platform/grafana/public-entry",
    "searxng": "charts/searxng",
    "open-webui": "charts/open-webui",
    "litellm": "deploy/platform/litellm/public-entry",
    "rancher": "deploy/platform/rancher/public-entry",
    "grafana-mcp": "charts/grafana-mcp",
    "syncthing": "charts/syncthing",
    "uptime-kuma": "charts/uptime-kuma",
}


def chart_values(owner: str) -> dict[str, object]:
    """Load the complete owner inputs, preserving any surrounding feature values."""
    source = (ROOT / CHARTS[owner] / "values.yaml").read_text()
    return cast("dict[str, object]", yaml.safe_load(source))


def public_entry(document: dict[str, object]) -> dict[str, object]:
    """Select the routes by schema, independently of the chart's directory."""
    entry = document.get("publicEntry", document)
    assert isinstance(entry, dict)
    assert isinstance(entry.get("routes"), list)
    return entry


def values(owner: str) -> dict[str, object]:
    """Read just the public-entry section for cross-owner topology checks."""
    return public_entry(chart_values(owner))


def render(owner=None) -> list[dict[str, object]]:
    docs = []
    for name in [owner] if owner else CHARTS:
        output = subprocess.check_output(
            ["helm", "template", name, str(ROOT / CHARTS[name])], text=True
        )
        docs.extend(
            d
            for d in yaml.safe_load_all(output)
            if d
            and (
                d["metadata"]["name"].startswith("public-web-")
                or d["metadata"]["name"].endswith("-browser")
            )
        )
    return docs
