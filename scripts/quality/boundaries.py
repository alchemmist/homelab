"""Issuer-alias boundaries the registered consumer list does not see.

A consumer is a YAML mapping that carries both ``ip`` and ``hostnames`` and names
the canonical issuer host. Prose mentions are not consumers. Newly introduced
alias sites fail until a human registers them; this module does not rewrite
addresses or treat the registered list as a complete audit by itself.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml
from common import ROOT, owned, tracked


def require(*, condition: bool, message: str) -> None:
    """Raise when a boundary predicate fails."""
    if not condition:
        raise ValueError(message)


def vendor_prefixes(root: Path) -> tuple[str, ...]:
    """Return vendor directory prefixes, or none when a fixture has no vendor contract."""
    path = root / "deploy/contracts/vendors.json"
    if not path.is_file():
        return ()
    vendors = json.loads(path.read_text())
    prefixes: list[str] = []
    for tree in vendors["trees"]:
        name = str(tree["path"]).strip("/")
        safe = bool(name) and name != "." and ".." not in Path(name).parts
        require(condition=safe, message="Unsafe vendor path")
        prefixes.append(name + "/")
    return tuple(prefixes)


def fixture_names(root: Path) -> list[str]:
    """List files under the three architecture roots of a temporary tree."""
    names: list[str] = []
    for base in ("ansible", "charts", "deploy"):
        folder = root / base
        if not folder.is_dir():
            continue
        names.extend(
            path.relative_to(root).as_posix()
            for path in folder.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
    return names


def yaml_name(name: str, prefixes: tuple[str, ...]) -> bool:
    """Return whether this path can hold an issuer host alias."""
    if any(name.startswith(prefix) for prefix in prefixes):
        return False
    if "/templates/" in name or name.endswith(".j2"):
        return False
    if not name.startswith(("ansible/", "charts/", "deploy/")):
        return False
    return name.endswith((".yml", ".yaml"))


def yaml_candidates(root: Path) -> list[str]:
    """Owned deploy, chart, and Ansible YAML, excluding templates and vendor trees."""
    prefixes = vendor_prefixes(root)
    names = owned(tracked()) if root.resolve() == ROOT.resolve() else fixture_names(root)
    return sorted({name for name in names if yaml_name(name, prefixes)})


def alias_sites(documents: list[object], hostname: str) -> Counter[tuple[str, ...]]:
    """Count issuer alias lists in already parsed YAML documents."""
    found: Counter[tuple[str, ...]] = Counter()

    def walk(node: object, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str):
                    continue
                walk(value, (*path, key))
        elif isinstance(node, list):
            for item in node:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("hostnames"), list)
                    and "ip" in item
                    and hostname in item["hostnames"]
                ):
                    found[path] += 1
                walk(item, path)

    for document in documents:
        walk(document, ())
    return found


def registered_issuer_sites(root: Path) -> tuple[str, set[tuple[str, tuple[str, ...]]]]:
    """Return the issuer hostname and the registered alias identities."""
    contract = json.loads((root / "deploy/contracts/infrastructure.json").read_text())
    route = contract["issuerTransport"]
    hostname = route["hostname"]
    named = isinstance(hostname, str) and bool(hostname)
    require(condition=named, message="Issuer hostname is missing")
    registered: set[tuple[str, tuple[str, ...]]] = set()
    for consumer in route["consumers"]:
        identity = (str(consumer["file"]), tuple(str(part) for part in consumer["path"]))
        fresh = identity not in registered
        require(condition=fresh, message="Duplicate registered issuer consumer")
        registered.add(identity)
    return hostname, registered


def unregistered_issuer_consumers(root: Path) -> list[str]:
    """Alias sites that are new or repeated beyond the registered consumer contract."""
    hostname, registered = registered_issuer_sites(root)
    seen: Counter[tuple[str, tuple[str, ...]]] = Counter()
    for name in yaml_candidates(root):
        text = (root / name).read_text()
        documents = list(yaml.safe_load_all(text))
        for path, count in alias_sites(documents, hostname).items():
            seen[(name, path)] += count
    extra: list[str] = []
    for identity, count in sorted(seen.items()):
        name, path = identity
        label = name + ":" + ".".join(path)
        if identity not in registered:
            extra.append(label)
        elif count != 1:
            extra.append(label + " repeated")
    for identity in sorted(registered):
        if identity not in seen:
            name, path = identity
            extra.append(name + ":" + ".".join(path) + " missing")
    return extra


def check(root: Path = ROOT) -> None:
    """Fail when an issuer alias is missing, repeated, or not registered."""
    extra = unregistered_issuer_consumers(root)
    require(
        condition=not extra,
        message="Unregistered issuer transport consumer: " + ", ".join(extra),
    )
