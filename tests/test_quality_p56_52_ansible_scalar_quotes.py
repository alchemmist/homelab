"""Keep repaired Ansible scalars semantically equal to their previous quotes."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "ansible" / "playbooks" / "identity-rbac.yml"
TIME = ROOT / "ansible" / "roles" / "debian_laptop" / "tasks" / "time.yml"
STRING_TAG = "tag:yaml.org,2002:str"
INTEGER_TAG = "tag:yaml.org,2002:int"
CHRONY_REGEXP = r"^pool\s+\S*debian\.pool\.ntp\.org\b"
FILE_MODE = "0644"
ARGV_LINE = '        argv: [kubectl, --kubeconfig, /etc/rancher/k3s/k3s.yaml, apply, -f, "-"]'
LOOKUP_ARGUMENT = "'file', playbook_dir + '/../../deploy/identity/observer-role.yaml')"
STDIN_VALUE = "{{ lookup(" + LOOKUP_ARGUMENT + " }}"
REGEXP_LINE = "    regexp: " + CHRONY_REGEXP
MODE_LINE = '    mode: "0644"'
NO_SHARED_ALIASES = 0
type LoaderType = type[yaml.SafeLoader | yaml.Loader]


def _as_node(value: object) -> yaml.Node:
    """Narrow a composed child to a YAML node."""
    if isinstance(value, yaml.Node):
        return value
    message = "expected a YAML node"
    raise TypeError(message)


def _scalars(text: str, loader: LoaderType) -> tuple[tuple[str, str], ...]:
    """Return every scalar tag and value in document order."""
    found: list[tuple[str, str]] = []

    def walk(node: yaml.Node) -> None:
        if isinstance(node, yaml.ScalarNode):
            found.append((node.tag, node.value))
            return
        if isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(_as_node(item))
            return
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                walk(_as_node(key))
                walk(_as_node(value))
            return
        message = "unsupported YAML node"
        raise TypeError(message)

    for document in yaml.compose_all(text, Loader=loader):
        walk(document)
    return tuple(found)


def _alias_count(text: str, loader: LoaderType) -> int:
    """Count shared node visits in the composed stream."""
    total = 0

    def walk(node: yaml.Node, seen: set[int]) -> None:
        nonlocal total
        identity = id(node)
        if identity in seen:
            total += 1
            return
        seen.add(identity)
        if isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(_as_node(item), seen)
        elif isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                walk(_as_node(key), seen)
                walk(_as_node(value), seen)

    for document in yaml.compose_all(text, Loader=loader):
        walk(document, set())
    return total


def _named_scalar(text: str, loader: LoaderType, name: str) -> yaml.ScalarNode:
    """Return the scalar whose mapping key is ``name``."""
    found: list[yaml.ScalarNode] = []

    def walk(node: yaml.Node) -> None:
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if isinstance(key, yaml.ScalarNode) and key.value == name:
                    if not isinstance(value, yaml.ScalarNode):
                        message = "expected a scalar value"
                        raise TypeError(message)
                    found.append(value)
                else:
                    walk(_as_node(value))
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(_as_node(item))

    for document in yaml.compose_all(text, Loader=loader):
        walk(document)
    if not found or found[1:]:
        message = "expected one named scalar"
        raise AssertionError(message)
    return found[0]


def test_observer_argv_dash_stays_a_double_quoted_string() -> None:
    """Quote the kubectl filename flag without changing the argument or stdin."""
    text = IDENTITY.read_text()
    lines = text.splitlines()
    stdin_line = "        stdin: " + '"' + STDIN_VALUE + '"'
    assert ARGV_LINE in lines
    assert stdin_line in lines
    single = text.replace(', "-"]', ", '-']", 1)
    for loader in (yaml.SafeLoader, yaml.Loader):
        assert _scalars(text, loader) == _scalars(single, loader)
        assert _alias_count(text, loader) == _alias_count(single, loader) == NO_SHARED_ALIASES
        stdin = _named_scalar(text, loader, "stdin")
        assert (stdin.tag, stdin.value) == (STRING_TAG, STDIN_VALUE)


def test_chrony_regexp_and_mode_keep_their_string_values() -> None:
    """Unquote only the regexp, and keep mode 0644 a decimal-looking string."""
    text = TIME.read_text()
    assert REGEXP_LINE in text.splitlines()
    assert MODE_LINE in text.splitlines()
    quoted = text.replace(REGEXP_LINE, f"    regexp: '{CHRONY_REGEXP}'", 1)
    bare_mode = text.replace(MODE_LINE, "    mode: 0644", 1)
    for loader in (yaml.SafeLoader, yaml.Loader):
        assert _scalars(text, loader) == _scalars(quoted, loader)
        assert _alias_count(text, loader) == NO_SHARED_ALIASES
        regexp = _named_scalar(text, loader, "regexp")
        mode = _named_scalar(text, loader, "mode")
        assert (regexp.tag, regexp.value) == (STRING_TAG, CHRONY_REGEXP)
        assert (mode.tag, mode.value) == (STRING_TAG, FILE_MODE)
        bare = _named_scalar(bare_mode, loader, "mode")
        assert bare.tag == INTEGER_TAG
        assert (bare.tag, bare.value) != (STRING_TAG, FILE_MODE)
