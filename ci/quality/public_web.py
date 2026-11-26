"""Derive the NL chart's namespace scope from reviewed publications in catalog order."""

import re
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
    pattern = r"(?m)^watchNamespaces:\n(?:  - [a-z0-9-]+\n)+"
    if len(re.findall(pattern, values)) != 1:
        raise ValueError("Expected one top-level watchNamespaces list")
    return re.sub(pattern, namespace_block(), values)


if __name__ == "__main__":
    VALUES.write_text(update_scope(VALUES.read_text()))
