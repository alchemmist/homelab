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


def values(owner) -> dict[str, object]:
    value: dict[str, object] = yaml.safe_load((ROOT / CHARTS[owner] / "values.yaml").read_text())
    if CHARTS[owner].startswith("deploy/"):
        return value
    return cast("dict[str, object]", value["publicEntry"])


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
