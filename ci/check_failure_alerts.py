#!/usr/bin/env python3
"""Offline workflow policy. --fix edits local JSON only; never contacts n8n."""

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple, TypedDict, cast

POLICY = "n8n-workflow-policy.json"


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def inside(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("policy paths must be repository-relative")
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("symlinks and paths outside the repository are forbidden")
    return path


class _ScanContext(NamedTuple):
    """Validated workflow policy roots, handler target and file references."""

    policy: dict[str, object]
    target: str
    handler: object


class _ScanState(TypedDict):
    """Accumulated findings, repairs and coverage flags across the scan."""

    errors: list[str]
    repairs: list[tuple[Path, object]]
    checked: int
    handler_seen: bool


class _Document(NamedTuple):
    """Positional identity of one workflow candidate inside a JSON file."""

    relative: str
    position: int
    is_list: bool


def _load_policy(root: Path) -> _ScanContext:
    """Load and validate the workflow failure policy before any scan."""
    policy = cast("dict[str, object]", load(inside(root, POLICY)))
    if (
        policy.get("version") != 1
        or not policy.get("handler_id")
        or not policy.get("workflow_roots")
    ):
        raise ValueError("invalid workflow policy")
    target = policy["handler_id"]
    if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", target):
        raise ValueError("invalid handler identity")
    handler = policy.get("handler_template")
    if handler:
        inside(root, cast("str", handler))
    return _ScanContext(policy=policy, target=target, handler=handler)


def _collect_workflow_files(root: Path, policy: dict[str, object]) -> set[Path]:
    """Collect plain JSON workflow files inside the configured roots."""
    files = set()
    for name in cast("list[object]", policy["workflow_roots"]):
        directory = inside(root, cast("str", name))
        if not directory.is_dir():
            raise ValueError("configured workflow root is missing")
        for path in directory.rglob("*"):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("symlinked workflow JSON is forbidden")
            if path.is_file() and path.suffix == ".json":
                files.add(path)
    return files


def _has_workflow_shape(w: dict[str, object], settings: object) -> bool:
    """Require list nodes, dict connections and dict settings."""
    return (
        isinstance(w["nodes"], list)
        and isinstance(w["connections"], dict)
        and isinstance(settings, dict)
    )


def _review_handler_workflow(
    w: dict[str, object], doc: _Document, context: _ScanContext, state: _ScanState
) -> None:
    """Enforce the reviewed error-handler workflow shape and trigger."""
    label = doc.relative + (f"#{doc.position}" if doc.is_list else "")
    settings = cast("dict[str, object]", w.get("settings", {}))
    if (
        w["name"] != context.policy["handler_name"]
        or doc.is_list
        or not any(
            isinstance(n, dict) and n.get("type") == "n8n-nodes-base.errorTrigger"
            for n in cast("list[object]", w["nodes"])
        )
    ):
        state["errors"].append(f"{label}: handler identity/trigger mismatch")
    if settings.get("errorWorkflow"):
        state["errors"].append(f"{label}: error handler must not have an error target (recursion)")


def _review_workflow(
    w: object,
    doc: _Document,
    state: _ScanState,
    context: _ScanContext,
    *,
    fix: bool,
) -> None:
    """Apply the failure-alert policy to one workflow candidate."""
    if not isinstance(w, dict) or not {"name", "nodes"} <= w.keys():
        return
    if "connections" not in w:
        state["errors"].append(f"{doc.relative}: workflow is missing connections")
        return
    state["checked"] += 1
    settings = w.get("settings", {})
    if not _has_workflow_shape(cast("dict[str, object]", w), settings):
        label = doc.relative + (f"#{doc.position}" if doc.is_list else "")
        state["errors"].append(f"{label}: invalid workflow shape; repair explicitly")
        return
    if doc.relative == context.handler:
        state["handler_seen"] = True
        _review_handler_workflow(cast("dict[str, object]", w), doc, context, state)
        return
    existing = cast("dict[str, object]", settings).get("errorWorkflow")
    if existing == context.target:
        return
    if existing not in (None, ""):
        label = doc.relative + (f"#{doc.position}" if doc.is_list else "")
        state["errors"].append(f"{label}: different error handler; refusing to overwrite")
        return
    if fix:
        w.setdefault("settings", {})["errorWorkflow"] = context.target
    else:
        state["errors"].append(
            f"{doc.relative}: missing settings.errorWorkflow; "
            "run python ci/check_failure_alerts.py --fix"
        )


def _review_documents(
    files: set[Path],
    root: Path,
    context: _ScanContext,
    state: _ScanState,
    *,
    fix: bool,
) -> None:
    """Scan every discovered workflow JSON file for policy compliance."""
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        try:
            document = load(path)
        except (ValueError, UnicodeError):
            state["errors"].append(f"{relative}: invalid/duplicate-key JSON; repair explicitly")
            continue
        original = copy.deepcopy(document)
        candidates = document if (is_list := isinstance(document, list)) else [document]
        for index, w in enumerate(candidates):
            doc = _Document(relative=relative, position=index, is_list=is_list)
            _review_workflow(w, doc, state, context, fix=fix)
        if document != original:
            state["repairs"].append((path, document))


def _finish_scan(root: Path, state: _ScanState, context: _ScanContext, *, fix: bool) -> int:
    """Report findings, apply reviewed local repairs, and return the exit code."""
    if context.handler and not state["handler_seen"]:
        state["errors"].append("configured handler template is missing or is not a workflow")
    if not state["checked"]:
        state["errors"].append("no workflow templates discovered; check policy roots")
    if state["errors"]:
        for error in state["errors"]:
            print(error, file=sys.stderr)
        if fix:
            print("No files changed: resolve conflicts before --fix.", file=sys.stderr)
        return 1
    for path, document in state["repairs"]:
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Fixed {path.relative_to(root)}")
    print(
        f"Workflow failure policy OK: {state['checked']} templates, "
        f"{len(state['repairs'])} files fixed; no live API calls."
    )
    return 0


def run(root: Path, fix: bool = False) -> int:
    root = root.resolve()
    context = _load_policy(root)
    files = _collect_workflow_files(root, context.policy)
    state = _ScanState(errors=[], repairs=[], checked=0, handler_seen=False)
    _review_documents(files, root, context, state, fix=fix)
    return _finish_scan(root, state, context, fix=fix)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Fill missing local settings; never overwrite a different handler",
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        return run(args.root, args.fix)
    except (ValueError, OSError):
        print(
            "Workflow policy/configuration error; no automatic repair. Check paths and JSON.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
