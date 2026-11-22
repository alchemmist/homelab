"""Deterministic boundary around an untrusted model. No credentials required."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal, NotRequired, TypedDict, cast

REPO = "alchemmist/blog"
UPDATES = "site/content/updates.md"
MAX_FILES = 200
MAX_INPUT_BYTES = 120_000
MAX_ENTRIES = 5


class PushEvent(TypedDict, total=False):
    """Push webhook fields consumed by the worker; other GitHub fields are ignored."""

    repository: Mapping[str, object]
    ref: str
    deleted: bool
    before: str
    after: str


class ChangedFile(TypedDict):
    """GitHub file metadata used for filtering; additional diff fields can be copied."""

    filename: str
    status: NotRequired[str]
    changes: NotRequired[int]
    patch: NotRequired[str]


class CommitInfo(TypedDict):
    """Nested git commit metadata, including the timestamp used for rendering."""

    message: str
    committer: dict[str, str]


class Commit(TypedDict):
    """Commit metadata indexed by the compared SHA."""

    sha: str
    commit: CommitInfo


class Comparison(TypedDict, total=False):
    """Relevant fields of a GitHub compare response."""

    files: list[ChangedFile]
    commits: list[Commit]
    status: str
    total_commits: int


class Context(TypedDict):
    """Filtered, size-limited compare data passed to the model."""

    files: list[dict[str, object]]
    recent_updates: str
    commits: list[dict[str, str]]


class RenderedEntry(TypedDict):
    """Text needed to render one entry, independent of model provenance."""

    text: str


class Entry(RenderedEntry):
    """Model entry attributed to at least one changed path."""

    source_paths: list[str]


class Decision(TypedDict):
    """Model output after the exact schema and provenance checks succeed."""

    should_update: bool
    reason: str
    entries: list[Entry]


class UnsafeInput(ValueError):
    """Value error raised on unsafe blog update input."""


def validate_event(event: PushEvent) -> bool:
    if event.get("repository", {}).get("full_name") != REPO:
        msg = "Unexpected repository"
        raise UnsafeInput(msg)
    if event.get("ref") != "refs/heads/main" or event.get("deleted"):
        return False
    sha_keys: tuple[Literal["before"], Literal["after"]] = ("before", "after")
    for key in sha_keys:
        if not re.fullmatch(r"[0-9a-f]{40}", event.get(key, "")):
            msg = "Invalid commit SHA"
            raise UnsafeInput(msg)
        if event[key] == "0" * 40:
            msg = "Branch creation/deletion needs manual review"
            raise UnsafeInput(msg)
    return True


def prepare(compare: Comparison, updates: str) -> Context | None:
    files = compare.get("files", [])
    if not files or len(files) > MAX_FILES:
        msg = "Missing or oversized file list; do not silently truncate"
        raise UnsafeInput(msg)
    # Github compare is limited to 300 files. Lower limit makes truncation fail closed.
    relevant = [
        f
        for f in files
        if f["filename"] != UPDATES and not f["filename"].startswith((".github/", "remark42/"))
    ]
    if not relevant:
        return None
    candidates: list[dict[str, object]] = []
    for f in relevant:
        name = f["filename"]
        if f.get("status") in ("removed", "renamed"):
            # Removals/renames still matter to the model, but are not new publications.
            pass
        binary_asset = name.lower().endswith(
            (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".ico",
                ".woff",
                ".woff2",
                ".mp4",
                ".pdf",
            )
        )
        if "patch" not in f and f.get("changes", 0) and not binary_asset:
            raise UnsafeInput("Missing text diff: " + name)
        if binary_asset:
            candidates.append({"filename": name, "status": f.get("status"), "binary_asset": True})
            continue
        fields: Mapping[str, object] = f
        candidates.append(
            {
                k: fields[k]
                for k in (
                    "filename",
                    "previous_filename",
                    "status",
                    "additions",
                    "deletions",
                    "patch",
                )
                if k in f
            }
        )
    context: Context = {
        "files": candidates,
        "recent_updates": updates,
        "commits": [
            {"sha": c["sha"], "message": c.get("commit", {}).get("message", "")}
            for c in compare.get("commits", [])
        ],
    }
    if len(json.dumps(context, ensure_ascii=False).encode()) > MAX_INPUT_BYTES:
        msg = "Analysis exceeds budget; manual review required"
        raise UnsafeInput(msg)
    return context


def validate_decision(raw: object, context: Context) -> Decision:
    """Model chooses a description, never a path to write or arbitrary Markdown."""
    if not isinstance(raw, dict) or set(raw) != {"should_update", "reason", "entries"}:
        msg = "Unexpected model schema"
        raise UnsafeInput(msg)
    if type(raw["should_update"]) is not bool or not isinstance(raw["reason"], str):
        msg = "Invalid decision types"
        raise UnsafeInput(msg)
    entries = raw["entries"]
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        msg = "Invalid entries"
        raise UnsafeInput(msg)
    if bool(entries) != raw["should_update"]:
        msg = "Inconsistent decision"
        raise UnsafeInput(msg)
    paths = {f["filename"] for f in context["files"]}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"text", "source_paths"}:
            msg = "Invalid entry schema"
            raise UnsafeInput(msg)
        text = entry["text"]
        if not isinstance(text, str) or not 1 <= len(text) <= 240:
            msg = "Invalid entry length"
            raise UnsafeInput(msg)
        # All formatting is performed by code. No links supplied by model.
        if any(c in text for c in "\n\r<>[]`\\") or re.search(r"https?://", text):
            msg = "Unsafe Markdown"
            raise UnsafeInput(msg)
        sources = entry["source_paths"]
        if (
            not isinstance(sources, list)
            or not sources
            or not all(isinstance(p, str) and p in paths for p in sources)
        ):
            msg = "Unsubstantiated entry"
            raise UnsafeInput(msg)
    return cast("Decision", raw)


def render(updates: str, entries: Sequence[RenderedEntry], timestamp: str) -> str:
    if not updates.startswith("---\n"):
        msg = "Missing front matter"
        raise UnsafeInput(msg)
    end = updates.find("\n---\n", 4)
    if end == -1:
        msg = "Unterminated front matter"
        raise UnsafeInput(msg)
    stamp = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        msg = "Timestamp must include timezone"
        raise UnsafeInput(msg)
    display_stamp = stamp.astimezone(dt.timezone(dt.timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")
    lines = [f"- [ ] *\\[{display_stamp}\\]* {e['text']}" for e in entries]
    # Prevent exact duplicate descriptions, including manually added ones.
    existing = {
        re.sub(r"^- \[[ x]\] \*\\\[.*?\\\]\*\s*", "", l).strip() for l in updates.splitlines()
    }
    lines = [l for l, e in zip(lines, entries, strict=True) if e["text"].strip() not in existing]
    if not lines:
        return updates
    offset = end + len("\n---\n")
    return updates[:offset] + "\n".join(lines) + "\n" + updates[offset:]
