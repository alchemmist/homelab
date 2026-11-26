"""Derive the NL chart's namespace scope from reviewed publications in catalog order."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "deploy/public-web/entrances.yaml"
VALUES = ROOT / "charts/traefik-edge/values.yaml"


def namespace_block() -> str:
    """Emit one watch list shared by the ingress provider and its RoleBindings."""
    catalog = yaml.safe_load(CATALOG.read_text())
    namespaces = catalog["nlWatchNamespaces"]
    return "watchNamespaces:\n" + "".join(f"  - {ns}\n" for ns in namespaces)


def update_scope(values: str) -> str:
    """Replace exactly one top-level watch list, preserving unrelated YAML verbatim."""
    root = yaml.compose(values, Loader=yaml.SafeLoader)
    if not isinstance(root, yaml.MappingNode):
        raise ValueError("Expected a top-level values mapping")
    entries = [(key, val) for key, val in root.value if key.value == "watchNamespaces"]
    if len(entries) != 1:
        raise ValueError("Expected exactly one watchNamespaces key")
    key, val = entries[0]
    if isinstance(val, yaml.SequenceNode) and val.value and not val.flow_style:
        end = val.value[-1].end_mark.index
    elif isinstance(val, yaml.SequenceNode) or val.tag == "tag:yaml.org,2002:null":
        end = val.end_mark.index
    else:
        raise ValueError("Expected watchNamespaces to be a list")
    return values[: key.start_mark.index] + namespace_block().rstrip("\n") + values[end:]


if __name__ == "__main__":
    original = VALUES.read_text()
    updated = update_scope(original)
    if updated != original:
        VALUES.write_text(updated)
