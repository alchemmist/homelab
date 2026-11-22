"""Render app-owned public access, without an aggregate chart/Application."""

import re
import subprocess
from pathlib import Path

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


def assert_status_upstream(conf: str) -> None:
    """Check the named HTTP upstream, not just the presence of a Gatus server line."""
    # Tokenize the checked-in policy subset, keeping quoted log formats opaque.
    # Braces and semicolons delimit directives even when several share a line.
    tokens = re.findall(
        r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\#[^\n]*|[^\s{};"'\#]+|[{};]""", conf
    )
    stack: list[tuple[str, ...]] = []
    directive: list[str] = []
    upstreams = []
    members = []
    for lexeme in tokens:
        if lexeme.startswith("#"):
            continue
        if lexeme not in {"{", "}", ";"}:
            directive.append(lexeme)
            continue
        if lexeme == "}":
            assert not directive
            assert stack
            stack.pop()
            continue
        assert directive
        header = tuple(directive)
        if any(block[0] == "upstream" for block in stack):
            members.append((lexeme, header))
        if lexeme == "{":
            if header[0] == "upstream":
                upstreams.append((tuple(stack), header))
            stack.append(header)
        directive.clear()
    assert not stack
    assert not directive
    assert upstreams == [((("http",),), ("upstream", "kuma"))], (
        "Unexpected status upstream topology"
    )
    assert members == [
        (";", ("zone", "kuma", "64k")),
        (";", ("server", "gatus.uptime-kuma.svc.cluster.local:80", "resolve")),
    ], "Unexpected backend in status upstream"


def chart_values(owner: str) -> dict[str, object]:
    """Load the complete owner inputs, preserving any surrounding feature values."""
    source = (ROOT / CHARTS[owner] / "values.yaml").read_text()
    document = yaml.safe_load(source)
    assert isinstance(document, dict), f"Expected mapping in {owner} chart values"
    return document


def public_entry(document: dict[str, object]) -> dict[str, object]:
    """Select the routes by schema, independently of the chart's directory."""
    entry = document.get("publicEntry", document)
    assert isinstance(entry, dict)
    assert isinstance(entry.get("routes"), list), "Expected public-entry routes list"
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
