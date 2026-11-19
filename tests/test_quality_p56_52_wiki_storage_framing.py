"""Document markers do not change the restored wiki-runtime volume identity."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "ansible" / "files" / "wiki-runtime-storage-socrat-0.yaml"
STRING_TAG = "tag:yaml.org,2002:str"
NO_SHARED_ALIASES = 0
PV_DOCUMENT = 0
PVC_DOCUMENT = 1
HOST_PATH = "/var/lib/rancher/k3s/storage/wiki-runtime-data-socrat-0-20261101"
PV_NAME = "wiki-runtime-data-socrat-0-20261101"
CLAIM_NAME = "wiki-runtime-data-socrat-0"
EXPECTED = (
    (PV_DOCUMENT, "apiVersion", "v1"),
    (PV_DOCUMENT, "kind", "PersistentVolume"),
    (PV_DOCUMENT, "metadata.name", PV_NAME),
    (PV_DOCUMENT, "spec.capacity.storage", "5Gi"),
    (PV_DOCUMENT, "spec.accessModes[0]", "ReadWriteOnce"),
    (PV_DOCUMENT, "spec.persistentVolumeReclaimPolicy", "Retain"),
    (PV_DOCUMENT, "spec.storageClassName", "local-path"),
    (PV_DOCUMENT, "spec.hostPath.path", HOST_PATH),
    (PV_DOCUMENT, "spec.hostPath.type", "Directory"),
    (PV_DOCUMENT, "spec.claimRef.namespace", "wiki"),
    (PV_DOCUMENT, "spec.claimRef.name", CLAIM_NAME),
    (
        PV_DOCUMENT,
        "spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].key",
        "kubernetes.io/hostname",
    ),
    (
        PV_DOCUMENT,
        "spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].operator",
        "In",
    ),
    (
        PV_DOCUMENT,
        "spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]",
        "socrat-0",
    ),
    (PVC_DOCUMENT, "apiVersion", "v1"),
    (PVC_DOCUMENT, "kind", "PersistentVolumeClaim"),
    (PVC_DOCUMENT, "metadata.name", CLAIM_NAME),
    (PVC_DOCUMENT, "metadata.namespace", "wiki"),
    (PVC_DOCUMENT, "spec.volumeName", PV_NAME),
    (PVC_DOCUMENT, "spec.accessModes[0]", "ReadWriteOnce"),
    (PVC_DOCUMENT, "spec.storageClassName", "local-path"),
    (PVC_DOCUMENT, "spec.resources.requests.storage", "5Gi"),
)
type LoaderType = type[yaml.SafeLoader | yaml.Loader]


def _as_node(value: object) -> yaml.Node:
    """Narrow a composed child to a YAML node."""
    if isinstance(value, yaml.Node):
        return value
    message = "expected a YAML node"
    raise TypeError(message)


def _scalars(node: yaml.Node, prefix: str) -> tuple[tuple[str, str, str], ...]:
    """Return path, tag, and value for every scalar under ``node``."""
    if isinstance(node, yaml.ScalarNode):
        return ((prefix, node.tag, node.value),)
    if isinstance(node, yaml.SequenceNode):
        found: list[tuple[str, str, str]] = []
        for index, item in enumerate(node.value):
            found.extend(_scalars(_as_node(item), f"{prefix}[{index}]"))
        return tuple(found)
    if isinstance(node, yaml.MappingNode):
        found = []
        for key, value in node.value:
            if not isinstance(key, yaml.ScalarNode):
                message = "expected a scalar key"
                raise TypeError(message)
            child = f"{prefix}.{key.value}" if prefix else key.value
            found.extend(_scalars(_as_node(value), child))
        return tuple(found)
    message = "unsupported YAML node"
    raise TypeError(message)


def _documents(text: str, loader: LoaderType) -> tuple[yaml.Node, ...]:
    """Compose every document in the manifest."""
    return tuple(yaml.compose_all(text, Loader=loader))


def _alias_count(node: yaml.Node, seen: set[int] | None = None) -> int:
    """Count nodes visited twice, which is how composed aliases stay shared."""
    if seen is None:
        seen = set()
    identity = id(node)
    if identity in seen:
        return 1
    seen.add(identity)
    total = 0
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            total += _alias_count(_as_node(item), seen)
    elif isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            total += _alias_count(_as_node(key), seen)
            total += _alias_count(_as_node(value), seen)
    return total


def _without_added_markers(text: str) -> str:
    """Drop the leading document start and both explicit document ends."""
    kept: list[str] = []
    removed_start = False
    for line in text.splitlines(keepends=True):
        if line == "---\n" and not removed_start:
            removed_start = True
            continue
        if line == "...\n":
            continue
        kept.append(line)
    return "".join(kept)


def test_wiki_runtime_storage_markers_keep_the_same_objects() -> None:
    """Framing markers leave both retained volume objects byte-identical in value."""
    text = MANIFEST.read_text()
    lines = text.splitlines()
    assert lines[0] == (
        "# Restored offline on 2026-11-01. This manifest does not copy or initialize data."
    )
    assert lines[1] == (
        "# Restore and verify the directory before binding this volume on a new host."
    )
    assert lines[2] == "---"
    assert lines[-1] == "..."
    assert ["...", "---"] in [lines[index : index + 2] for index in range(len(lines) - 1)]
    stripped = _without_added_markers(text)
    assert stripped != text
    for loader in (yaml.SafeLoader, yaml.Loader):
        current = _documents(text, loader)
        original = _documents(stripped, loader)
        assert len(current) == len(original) == len({PV_DOCUMENT, PVC_DOCUMENT})
        assert all(isinstance(document, yaml.Node) for document in current)
        pairs = tuple(
            (index, path, value)
            for index, document in enumerate(current)
            for path, tag, value in _scalars(document, "")
            if tag == STRING_TAG
        )
        assert pairs == EXPECTED
        assert tuple(_scalars(document, "") for document in current) == tuple(
            _scalars(document, "") for document in original
        )
        assert sum(_alias_count(document) for document in current) == NO_SHARED_ALIASES
