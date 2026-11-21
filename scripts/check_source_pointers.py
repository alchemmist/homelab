#!/usr/bin/env python3
"""Offline local Argo source/value-file and selected current-document pointers.
No rendering, download, live reconciliation or historical-document rewrites.
External chart contents, web routes and Markdown fragments are not verified.
"""

import json
import re
import urllib.parse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def inside(root, path):
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Source pointer escapes repository")
    return path


def applications(root, directory, repo):
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
        refs = {}
        for source in sources:
            if "ref" in source:
                ref = source["ref"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", ref) or ref in refs:
                    raise ValueError("Duplicate/invalid source ref: " + file.name)
                refs[ref] = source
        for source in sources:
            local = source["repoURL"] == repo
            path = source.get("path")
            if local:
                if source.get("targetRevision") != "main":
                    raise ValueError(
                        "Cannot verify non-main local source against current checkout: " + file.name
                    )
                if path:
                    if Path(path).is_absolute():
                        raise ValueError(
                            "Argo source path must be repository-relative: " + file.name
                        )
                    target = inside(root, root / path)
                    if not target.is_dir():
                        raise ValueError("Missing local source directory: " + file.name)
                    pointers += 1
                    chart = inside(root, target / "Chart.yaml")
                    defaults = inside(root, target / "values.yaml")
                    if chart.is_file() and defaults.is_file():
                        active_values.add(defaults)
                    if "helm" in source and not chart.is_file():
                        raise ValueError("Missing Helm Chart.yaml: " + file.name)
                elif not source.get("ref"):
                    raise ValueError("Local source requires path or ref: " + file.name)
            for value in source.get("helm", {}).get("valueFiles", []):
                if value.startswith("$"):
                    match = re.fullmatch(r"\$([^/]+)/(.+)", value)
                    if not match or match[1] not in refs:
                        raise ValueError("Undefined value-file ref: " + file.name)
                    if Path(match[2]).is_absolute():
                        raise ValueError("Ref values must be repository-relative: " + file.name)
                    ref = refs[match[1]]
                    if ref["repoURL"] != repo or ref.get("targetRevision") != "main":
                        raise ValueError(
                            "Cannot verify nonlocal/non-main value-file ref: " + file.name
                        )
                    target = inside(root, root / match[2])
                elif local and path:
                    if Path(value).is_absolute():
                        raise ValueError("Helm values must be repository-relative: " + file.name)
                    target = inside(root, root / path / value)
                else:
                    raise ValueError("Cannot verify external relative values offline: " + file.name)
                # Deliberately strict even with ignoreMissingValueFiles. Optional
                # values need a separately reviewed contract, not silently skipping.
                if not target.is_file():
                    raise ValueError("Missing local values file: " + file.name)
                pointers += 1
                active_values.add(target)
    return len(names), pointers, values_by_owner


def check(root=ROOT):
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
        file = inside(root, root / name)
        text = file.read_text()
        for link in re.findall(r"\]\(([^\s)]+)", text):
            url = urllib.parse.urlsplit(link)
            if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
                continue
            target = inside(root, file.parent / urllib.parse.unquote(url.path))
            if not target.exists():
                raise ValueError("Broken local document link: " + name)
    for binding in c["currentValues"]:
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
    return count, pointers


if __name__ == "__main__":
    count, pointers = check()
    print(
        f"Source pointers OK: {count} Applications, {pointers} local source/value pointers and registered current docs"
    )
