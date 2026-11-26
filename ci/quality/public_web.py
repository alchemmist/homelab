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


if __name__ == "__main__":
    before, scope = VALUES.read_text().split("watchNamespaces:\n")
    _, after = scope.split("apiEndpoint:")
    VALUES.write_text(before + namespace_block() + "apiEndpoint:" + after)
