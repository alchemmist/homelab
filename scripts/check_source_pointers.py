#!/usr/bin/env python3
"""Offline local Argo source/value-file and selected current-document pointers.
No rendering, download, live reconciliation or historical-document rewrites.
External chart contents, web routes and Markdown fragments are not verified.
"""

import json
import re
import urllib.parse
from pathlib import Path
from typing import NamedTuple, TypedDict, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]


def inside(root, path):
    """Document this public function."""
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Source pointer escapes repository")
    return path


def _gather_refs(name: str, sources: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """Collect and validate the file-scoped ref names declared by the sources."""
    refs: dict[str, dict[str, object]] = {}
    for source in sources:
        if "ref" in source:
            ref = cast("str", source["ref"])
            if not re.fullmatch(r"[A-Za-z0-9_-]+", ref) or ref in refs:
                raise ValueError("Duplicate/invalid source ref: " + name)
            refs[ref] = source
    return refs


class _ScanContext(NamedTuple):
    """File-scoped state shared by the per-source pointer validators."""

    root: Path
    repo: str
    name: str
    refs: dict[str, dict[str, object]]
    active_values: set[Path]


def _local_chart_targets(context: _ScanContext, source: dict[str, object], path: str) -> int:
    """Validate one local source directory's chart and default values pointers."""
    root, _, name, _, active_values = context
    if Path(path).is_absolute():
        raise ValueError("Argo source path must be repository-relative: " + name)
    target = inside(root, root / path)
    if not target.is_dir():
        raise ValueError("Missing local source directory: " + name)
    chart = inside(root, target / "Chart.yaml")
    defaults = inside(root, target / "values.yaml")
    if chart.is_file() and defaults.is_file():
        active_values.add(defaults)
    if "helm" in source and not chart.is_file():
        raise ValueError("Missing Helm Chart.yaml: " + name)
    return 1


def _local_source_targets(context: _ScanContext, source: dict[str, object], path: object) -> int:
    """Validate a local source's chart directory or required ref form."""
    local = source["repoURL"] == context.repo
    if local:
        if source.get("targetRevision") != "main":
            raise ValueError(
                "Cannot verify non-main local source against current checkout: " + context.name
            )
        if path:
            return _local_chart_targets(context, source, cast("str", path))
        if not source.get("ref"):
            raise ValueError("Local source requires path or ref: " + context.name)
    return 0


def _ref_value_target(context: _ScanContext, value: str) -> Path:
    """Resolve a $ref-scoped value file to its registered and local path."""
    root, repo, name, refs, _ = context
    match = re.fullmatch(r"\$([^/]+)/(.+)", value)
    if not match or match[1] not in refs:
        raise ValueError("Undefined value-file ref: " + name)
    if Path(match[2]).is_absolute():
        raise ValueError("Ref values must be repository-relative: " + name)
    ref = refs[match[1]]
    if ref["repoURL"] != repo or ref.get("targetRevision") != "main":
        raise ValueError("Cannot verify nonlocal/non-main value-file ref: " + name)
    return inside(root, root / match[2])


def _value_targets(
    context: _ScanContext,
    source: dict[str, object],
    *,
    local: bool,
    path: object,
) -> int:
    """Validate every Helm value file of one source against repository relative paths."""
    pointers = 0
    for value in source.get("helm", {}).get("valueFiles", []):
        target = _resolve_value_target(context, value, local=local, path=path)
        # Deliberately strict even with ignoreMissingValueFiles. Optional
        # values need a separately reviewed contract, not silently skipping.
        if not target.is_file():
            raise ValueError("Missing local values file: " + context.name)
        pointers += 1
        context.active_values.add(target)
    return pointers


def _resolve_value_target(
    context: _ScanContext, value: object, *, local: bool, path: object
) -> Path:
    """Resolve one value-file entry to a local path using its declared scope."""
    if isinstance(value, str) and value.startswith("$"):
        return _ref_value_target(context, value)
    if local and path:
        text = cast("str", value)
        if Path(text).is_absolute():
            raise ValueError("Helm values must be repository-relative: " + context.name)
        return inside(context.root, context.root / cast("str", path) / text)
    raise ValueError("Cannot verify external relative values offline: " + context.name)


def applications(root, directory, repo):
    """Document this public function."""
    base = inside(root, root / directory)
    if not base.is_dir():
        raise ValueError("Missing Application directory")
    files = sorted(base.rglob("*.yaml"))
    if not files:
        raise ValueError("Empty Application inventory")
    names = set()
    values_by_owner = {}
    pointers = 0
    for file in files:
        app = yaml.safe_load(inside(root, file).read_text())
        if app.get("kind") != "Application":
            raise ValueError("Expected Application: " + file.name)
        identity = (app["metadata"].get("namespace", "argocd"), app["metadata"]["name"])
        if identity in names:
            raise ValueError("Duplicate Application identity: " + file.name)
        names.add(identity)
        active_values = values_by_owner.setdefault(identity, set())
        spec = app["spec"]
        if ("source" in spec) == ("sources" in spec):
            raise ValueError("Require exactly one source/sources form: " + file.name)
        sources = spec.get("sources", [spec.get("source")])
        if not sources:
            raise ValueError("Empty Application sources: " + file.name)
        refs = _gather_refs(file.name, sources)
        context = _ScanContext(root, repo, file.name, refs, active_values)
        for source in sources:
            path = source.get("path")
            pointers += _local_source_targets(context, source, path)
            pointers += _value_targets(context, source, local=source["repoURL"] == repo, path=path)
    return len(names), pointers, values_by_owner


class _CurrentValuesBinding(TypedDict):
    source: str
    application: str
    path: list[str]
    documents: list[str]


def _document_links(root: Path, name: str) -> None:
    """Verify every relative link in a registered document resolves locally."""
    file = inside(root, root / name)
    text = file.read_text()
    for link in re.findall(r"\]\(([^\s)]+)", text):
        url = urllib.parse.urlsplit(link)
        if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
            continue
        target = inside(root, file.parent / urllib.parse.unquote(url.path))
        if not target.exists():
            raise ValueError("Broken local document link: " + name)


def _current_values(
    root: Path, binding: _CurrentValuesBinding, active_values: dict[tuple[str, str], set[Path]]
) -> None:
    """Verify a documented current value is live and quoted in its documents."""
    source = inside(root, root / binding["source"])
    owner = ("argocd", binding["application"])
    if source not in active_values.get(owner, set()):
        raise ValueError("Documented values are not consumed by their registered Application")
    value = yaml.safe_load(source.read_text())
    for key in binding["path"]:
        value = value[key]
    if not isinstance(value, str) or not value:
        raise ValueError("Expected nonempty current-value pointer")
    for name in binding["documents"]:
        if "`" + value + "`" not in inside(root, root / name).read_text():
            raise ValueError("Current documentation value drift: " + name)


def check(root=ROOT):
    """Document this public function."""
    c = json.loads((root / "deploy/contracts/source-pointers.json").read_text())
    if c["schemaVersion"] != 1:
        raise ValueError("Unsupported source pointer schema")
    source = yaml.safe_load(inside(root, root / c["rootApplication"]).read_text())["spec"]["source"]
    if (
        source["repoURL"] != c["repoURL"]
        or source["path"] != c["applicationDirectory"]
        or source["targetRevision"] != "main"
    ):
        raise ValueError("Root Application no longer owns the checked source directory")
    count, pointers, active_values = applications(root, c["applicationDirectory"], c["repoURL"])
    for name in c["documents"]:
        _document_links(root, name)
    for binding in c["currentValues"]:
        _current_values(root, binding, active_values)
    return count, pointers


if __name__ == "__main__":
    count, pointers = check()
    print(
        f"Source pointers OK: {count} Applications, {pointers} local source/value pointers and registered current docs"
    )
