"""Keep four Helm appVersion values plain strings with unchanged text."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
STRING_TAG = "tag:yaml.org,2002:str"
NO_SHARED_ALIASES = 0
CHARTS = (
    ("charts/netbird/Chart.yaml", "netbird", "0.1.0", "0.82.0"),
    ("charts/pr-agent/Chart.yaml", "pr-agent", "0.1.0", "0.49.0"),
    ("charts/syncthing/Chart.yaml", "syncthing", "0.2.0", "2.1.3"),
    ("charts/x-ui/Chart.yaml", "x-ui", "0.3.1", "3.10.2"),
)
type LoaderType = type[yaml.SafeLoader | yaml.Loader]


def _as_node(value: object) -> yaml.Node:
    """Narrow a composed child to a YAML node."""
    if isinstance(value, yaml.Node):
        return value
    message = "expected a YAML node"
    raise TypeError(message)


def _node_signature(node: yaml.Node) -> tuple[object, ...]:
    """Return tag, value, order, and nested structure for one composed node."""
    if isinstance(node, yaml.ScalarNode):
        return ("scalar", node.tag, node.value)
    if isinstance(node, yaml.SequenceNode):
        nested = tuple(_node_signature(_as_node(item)) for item in node.value)
        return ("sequence", node.tag, nested)
    if isinstance(node, yaml.MappingNode):
        pairs = tuple(
            (_node_signature(_as_node(key)), _node_signature(_as_node(value)))
            for key, value in node.value
        )
        return ("mapping", node.tag, pairs)
    message = "unsupported YAML node"
    raise TypeError(message)


def _stream_signature(text: str, loader: LoaderType) -> tuple[tuple[object, ...], ...]:
    """Compose every document, including scalar tags and alias identity."""
    return tuple(_node_signature(document) for document in yaml.compose_all(text, Loader=loader))


def _count_shared_nodes(node: yaml.Node, seen: set[int], shared: list[int]) -> None:
    """Count nodes visited twice, which is how composed aliases stay shared."""
    identity = id(node)
    if identity in seen:
        shared.append(identity)
        return
    seen.add(identity)
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _count_shared_nodes(_as_node(item), seen, shared)
    elif isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            _count_shared_nodes(_as_node(key), seen, shared)
            _count_shared_nodes(_as_node(value), seen, shared)


def _alias_count(text: str, loader: LoaderType) -> int:
    """Return the number of shared node visits in the composed stream."""
    total = 0
    for document in yaml.compose_all(text, Loader=loader):
        shared: list[int] = []
        _count_shared_nodes(document, set(), shared)
        total += len(shared)
    return total


def _child(node: yaml.Node, name: str) -> yaml.Node:
    """Return the mapping value whose scalar key equals ``name``."""
    if not isinstance(node, yaml.MappingNode):
        message = "expected a mapping"
        raise TypeError(message)
    for key, value in node.value:
        if isinstance(key, yaml.ScalarNode) and key.value == name:
            return _as_node(value)
    message = "missing mapping key"
    raise KeyError(message)


def _scalar(node: yaml.Node, name: str) -> yaml.ScalarNode:
    """Return one mapping scalar."""
    value = _child(node, name)
    if not isinstance(value, yaml.ScalarNode):
        message = "expected a scalar"
        raise TypeError(message)
    return value


def test_chart_app_versions_stay_plain_strings() -> None:
    """Drop redundant appVersion quotes without changing chart identity or tags."""
    for relative, name, version, app_version in CHARTS:
        text = (ROOT / relative).read_text()
        if name == "syncthing":
            # Version upgrades remain independent of the unchanged quote/tag proof.
            image = yaml.safe_load((ROOT / "charts/syncthing/values.yaml").read_text())["image"]
            release = image["tag"]
            assert isinstance(release, str)
            app_version = release
        plain = f"appVersion: {app_version}"
        quoted = f'appVersion: "{app_version}"'
        assert plain in text.splitlines()
        assert quoted not in text
        restored = text.replace(plain, quoted, 1)
        for loader in (yaml.SafeLoader, yaml.Loader):
            assert _stream_signature(text, loader) == _stream_signature(restored, loader)
            assert _alias_count(text, loader) == _alias_count(restored, loader) == NO_SHARED_ALIASES
            document = yaml.compose(text, Loader=loader)
            if not isinstance(document, yaml.Node):
                message = "expected one chart document"
                raise TypeError(message)
            assert _scalar(document, "name").value == name
            assert _scalar(document, "version").value == version
            app = _scalar(document, "appVersion")
            assert (app.tag, app.value, app.style) == (STRING_TAG, app_version, None)


@pytest.mark.parametrize("violation", ["version", "quotes", "identity"])
def test_current_owner_version_input_does_not_hide_drift(
    monkeypatch: pytest.MonkeyPatch, violation: str
) -> None:
    """Keep current image consistency, exact metadata and scalar-style negatives."""
    test_chart_app_versions_stay_plain_strings()
    original = Path.read_text

    def changed(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        text = original(path, encoding=encoding, errors=errors)
        if path == ROOT / "charts/syncthing/Chart.yaml":
            before, after = {
                "version": ("appVersion: 2.1.7", "appVersion: 99.0.0"),
                "quotes": ("appVersion: 2.1.7", 'appVersion: "2.1.7"'),
                "identity": ("name: syncthing", "name: unreviewed"),
            }[violation]
            assert before in text
            text = text.replace(before, after, 1)
        return text

    monkeypatch.setattr(Path, "read_text", changed)
    with pytest.raises(AssertionError):
        test_chart_app_versions_stay_plain_strings()
