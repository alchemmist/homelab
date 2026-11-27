"""Preserve the retired n8n Fleet CPU limit as a double-quoted string."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "deploy" / "n8n" / "values.yaml"
CPU_LIMIT_SOURCE = '    cpu: "1"'
SINGLE_QUOTED_CPU_LIMIT = "    cpu: '1'"
BARE_CPU_LIMIT = "    cpu: 1"
STRING_TAG = "tag:yaml.org,2002:str"
INTEGER_TAG = "tag:yaml.org,2002:int"
BOOLEAN_TAG = "tag:yaml.org,2002:bool"
IMAGE = (
    "ghcr.io/alchemmist/n8n@sha256:0ffba3a289722fc216ee5e135c3acaeb4b3484e267aeba42df9c8f2e39e831df"
)
NO_SHARED_ALIASES = 0
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


def _scalar(node: yaml.Node, *path: str) -> yaml.ScalarNode:
    """Walk mapping keys and require the final node to be a scalar."""
    current = node
    for name in path:
        current = _child(current, name)
    if not isinstance(current, yaml.ScalarNode):
        message = "expected a scalar"
        raise TypeError(message)
    return current


def _first_document(text: str, loader: LoaderType) -> yaml.Node:
    """Compose the only document in this retired values file."""
    document = yaml.compose(text, Loader=loader)
    if not isinstance(document, yaml.Node):
        message = "expected one YAML document"
        raise TypeError(message)
    return document


def test_retired_n8n_cpu_limit_stays_a_double_quoted_string() -> None:
    """Keep the Fleet CPU limit quoted so YAML does not coerce it to an integer."""
    text = VALUES.read_text()
    assert CPU_LIMIT_SOURCE in text.splitlines()
    assert SINGLE_QUOTED_CPU_LIMIT not in text
    single = text.replace(CPU_LIMIT_SOURCE, SINGLE_QUOTED_CPU_LIMIT, 1)
    bare = text.replace(CPU_LIMIT_SOURCE, BARE_CPU_LIMIT, 1)
    for loader in (yaml.SafeLoader, yaml.Loader):
        assert _stream_signature(text, loader) == _stream_signature(single, loader)
        assert _alias_count(text, loader) == _alias_count(single, loader) == NO_SHARED_ALIASES
        assert _stream_signature(text, loader) != _stream_signature(bare, loader)
        cpu = _scalar(_first_document(text, loader), "resources", "limits", "cpu")
        assert (cpu.tag, cpu.value) == (STRING_TAG, "1")
        bare_cpu = _scalar(_first_document(bare, loader), "resources", "limits", "cpu")
        assert (bare_cpu.tag, bare_cpu.value) == (INTEGER_TAG, "1")

    document = _first_document(text, yaml.SafeLoader)
    assert _scalar(document, "image").value == IMAGE
    assert _scalar(document, "nodeName").value == "socrat-1"
    assert _scalar(document, "host").value == "n8n.socrat.alchemmist.xyz"
    assert _scalar(document, "webhookUrl").value == "https://n8n.socrat.alchemmist.xyz/"
    assert _scalar(document, "persistence", "storageClass").value == "local-path"
    assert _scalar(document, "persistence", "size").value == "5Gi"
    assert _scalar(document, "resources", "requests", "cpu").value == "100m"
    assert _scalar(document, "resources", "requests", "memory").value == "256Mi"
    assert _scalar(document, "resources", "limits", "memory").value == "1Gi"
    enabled = _scalar(document, "ingress", "enabled")
    assert (enabled.tag, enabled.value) == (BOOLEAN_TAG, "true")
