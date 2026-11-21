#!/usr/bin/env python3
"""Offline classification gate for literal Helm entrypoints in Ansible YAML.

Not an execution allowlist or a semantic audit of every operational script.
"""

import json
import re
from pathlib import Path
from typing import TypedDict

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM = re.compile(r"\bhelm\s+(?:upgrade|install)\b|\bkubernetes\.core\.helm\b")
STATUSES = {
    "retired",
    "guarded-bootstrap",
    "review-required",
    "excluded-vpn",
    "excluded-gpu",
    "deferred-backup",
}


class _Entrypoint(TypedDict):
    path: str
    status: str
    reason: str
    owners: list[str]


def _validate_classification(root: Path, entry: _Entrypoint) -> None:
    """Require a resolvable, well-reasoned entrypoint with real source owners."""
    name = entry["path"]
    target = root / name
    if (
        not target.resolve().is_relative_to(root.resolve())
        or not target.is_file()
        or entry["status"] not in STATUSES
        or not entry["reason"]
    ):
        raise ValueError("Invalid operational classification: " + name)
    for owner in entry["owners"]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", owner):
            raise ValueError("Invalid operational source owner: " + name)
        if not (root / "deploy/argocd/apps" / f"{owner}.yaml").is_file():
            raise ValueError("Missing operational source owner: " + name)


def _validate_retired(root: Path, entry: _Entrypoint) -> None:
    """Require a retired entrypoint's play to refuse with source pointers."""
    name = entry["path"]
    plays = yaml.safe_load((root / name).read_text())
    if not isinstance(plays, list) or len(plays) != 1:
        raise ValueError("Retired follow-up play: " + name)
    play = plays[0]
    if (
        set(play) != {"name", "hosts", "gather_facts", "become", "any_errors_fatal", "tasks"}
        or play["gather_facts"] is not False
        or play["become"] is not False
        or play["any_errors_fatal"] is not True
        or len(play["tasks"]) != 1
    ):
        raise ValueError("Retired entrypoint side effects: " + name)
    task = play["tasks"][0]
    if set(task) != {"name", "ansible.builtin.fail", "tags"} or "always" not in task["tags"]:
        raise ValueError("Retired entrypoint must refuse: " + name)
    for owner in entry["owners"]:
        if f"deploy/argocd/apps/{owner}.yaml" not in task["ansible.builtin.fail"]["msg"]:
            raise ValueError("Retired refusal missing source pointer: " + name)


def _helm_holders(root: Path) -> set[str]:
    """Scan the Ansible tree for literal Helm entrypoint usage."""
    found = set()
    for p in (root / "ansible").rglob("*.yml"):
        if not p.resolve().is_relative_to(root.resolve()):
            raise ValueError("Operational scan symlink escapes repository")
        if HELM.search(p.read_text()):
            found.add(p.relative_to(root).as_posix())
    return found


def check(root=ROOT):
    """Check the requested inputs."""
    c = json.loads((root / "deploy/contracts/operational-entrypoints.json").read_text())
    if c["schemaVersion"] != 1:
        raise ValueError("Unsupported entrypoint schema")
    entries = {}
    for entry in c["entries"]:
        name = entry["path"]
        if name in entries:
            raise ValueError("Duplicate operational entrypoint")
        entries[name] = entry
        _validate_classification(root, entry)
        if entry["status"] == "retired":
            _validate_retired(root, entry)
    found = _helm_holders(root)
    if found - set(entries):
        raise ValueError(
            "Unclassified literal Helm entrypoints: " + str(sorted(found - set(entries)))
        )
    for name, entry in entries.items():
        if entry["status"] not in {"retired", "guarded-bootstrap"} and name not in found:
            raise ValueError("Stale Helm classification; re-review removal: " + name)
    return len(entries), len(found)


if __name__ == "__main__":
    count, found = check()
    print(
        f"Operational classification OK: {count} scoped records, {found} literal Helm matches; review-required/excluded entries are not certified"
    )
