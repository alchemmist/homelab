"""Promtool unit scalars that must stay strings keep double quotes."""

from __future__ import annotations

from pathlib import Path

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

_FIXTURE = Path(__file__).resolve().parent / "service-availability.test.yml"
_EMPTY_LABEL = "{}"
_REPEAT_VALUE = "0x20"
_EMPTY_LABEL_QUOTES = 321
_REPEAT_VALUE_QUOTES = 37
_STRING_TAG = "tag:yaml.org,2002:str"
_DOUBLE_QUOTE = '"'
type _QuotedScalar = tuple[str, str | None, str]


def _compose(text: str, loader: type[yaml.SafeLoader | yaml.Loader]) -> Node:
    """Compose one YAML document with the requested loader."""
    node = yaml.compose(text, Loader=loader)
    assert isinstance(node, Node)
    return node


def _child_nodes(current: Node) -> tuple[Node, ...]:
    """Return mapping and sequence children, ignoring scalar values."""
    if isinstance(current, SequenceNode) and isinstance(current.value, list):
        return tuple(item for item in current.value if isinstance(item, Node))
    if isinstance(current, MappingNode) and isinstance(current.value, list):
        children: list[Node] = []
        for pair in current.value:
            if isinstance(pair, tuple):
                children.extend(item for item in pair if isinstance(item, Node))
        return tuple(children)
    return ()


def _string_quote_styles(node: Node) -> tuple[tuple[_QuotedScalar, ...], int]:
    """Collect string scalar styles and count shared alias nodes."""
    seen: set[int] = set()
    styles: list[_QuotedScalar] = []
    aliases = 0

    def visit(current: Node) -> None:
        nonlocal aliases
        marker = id(current)
        if marker in seen:
            aliases += 1
            return
        seen.add(marker)
        if isinstance(current, ScalarNode) and isinstance(current.value, str):
            style = current.style if isinstance(current.style, str) else None
            styles.append((current.value, style, current.tag))
            return
        for child in _child_nodes(current):
            visit(child)

    visit(node)
    return tuple(styles), aliases


def _structure(node: Node) -> tuple[object, ...]:
    """Return tags, values, and collection shape without quote style."""
    if isinstance(node, ScalarNode):
        return ("scalar", node.tag, node.value)
    children = tuple(_structure(child) for child in _child_nodes(node))
    if isinstance(node, SequenceNode):
        return ("sequence", node.tag, node.flow_style, children)
    if isinstance(node, MappingNode):
        return ("mapping", node.tag, node.flow_style, children)
    return ("node", node.tag, children)


def test_service_availability_required_quotes_stay_double_quoted_strings() -> None:
    """Preserve empty-label and repeat-value strings under both loaders."""
    text = _FIXTURE.read_text(encoding="utf-8")
    assert text.count(f"'{_EMPTY_LABEL}'") == 0
    assert text.count(f"'{_REPEAT_VALUE}'") == 0
    assert text.count(f'"{_EMPTY_LABEL}"') == _EMPTY_LABEL_QUOTES
    assert text.count(f'"{_REPEAT_VALUE}"') == _REPEAT_VALUE_QUOTES
    safe = _compose(text, yaml.SafeLoader)
    base = _compose(text, yaml.Loader)
    assert _structure(safe) == _structure(base)
    styles, aliases = _string_quote_styles(safe)
    assert aliases == 0
    empty = [(style, tag) for value, style, tag in styles if value == _EMPTY_LABEL]
    repeated = [(style, tag) for value, style, tag in styles if value == _REPEAT_VALUE]
    assert empty == [(_DOUBLE_QUOTE, _STRING_TAG)] * _EMPTY_LABEL_QUOTES
    assert repeated == [(_DOUBLE_QUOTE, _STRING_TAG)] * _REPEAT_VALUE_QUOTES
