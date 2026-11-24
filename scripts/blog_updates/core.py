"""Deterministic boundary around an untrusted model. No credentials required."""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPO = "alchemmist/blog"
UPDATES = "site/content/updates.md"
MAX_FILES = 200
MAX_INPUT_BYTES = 120_000
MAX_ENTRIES = 5
# GitHub compare answers carry at most this many files and commits per page.
COMPARE_PAGE_LIMIT = 100
# GitHub returns at most this many files in one compare response.
MAX_COMPARE_FILES = 300
# A model entry is a one-line announcement; 240 characters bound it.
MAX_ENTRY_CHARS = 240
# GitHub refuses a compare beyond 1000 commits; reject below the API cliff.
MAX_COMPARE_COMMITS = 1_000


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


class UnsafeInputError(ValueError):
    """Value error raised on unsafe blog update input."""


def validate_event(event: PushEvent) -> bool:
    """Accept only a forward push of the reviewed repository branch."""
    if event.get("repository", {}).get("full_name") != REPO:
        msg = "Unexpected repository"
        raise UnsafeInputError(msg)
    if event.get("ref") != "refs/heads/main" or event.get("deleted"):
        return False
    sha_keys: tuple[Literal["before"], Literal["after"]] = ("before", "after")
    for key in sha_keys:
        if not re.fullmatch(r"[0-9a-f]{40}", event.get(key, "")):
            msg = "Invalid commit SHA"
            raise UnsafeInputError(msg)
        if event[key] == "0" * 40:
            msg = "Branch creation/deletion needs manual review"
            raise UnsafeInputError(msg)
    return True


def prepare(compare: Comparison, updates: str) -> Context | None:
    """Build the model context from a compare and the updates snapshot."""
    files = compare.get("files", [])
    if not files or len(files) > MAX_FILES:
        msg = "Missing or oversized file list; do not silently truncate"
        raise UnsafeInputError(msg)
    # Github compare is limited to 300 files. Lower limit makes truncation fail closed.
    relevant = [
        f
        for f in files
        if f["filename"] != UPDATES
        and not f["filename"].startswith((".github/", "remark42/"))
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
            raise UnsafeInputError("Missing text diff: " + name)
        if binary_asset:
            candidates.append(
                {"filename": name, "status": f.get("status"), "binary_asset": True}
            )
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
        raise UnsafeInputError(msg)
    return context


def validate_decision(raw: object, context: Context) -> Decision:
    """Model chooses a description, never a path to write or arbitrary Markdown."""
    if not isinstance(raw, dict) or set(raw) != {"should_update", "reason", "entries"}:
        msg = "Unexpected model schema"
        raise UnsafeInputError(msg)
    if type(raw["should_update"]) is not bool or not isinstance(raw["reason"], str):
        msg = "Invalid decision types"
        raise UnsafeInputError(msg)
    entries = raw["entries"]
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        msg = "Invalid entries"
        raise UnsafeInputError(msg)
    if bool(entries) != raw["should_update"]:
        msg = "Inconsistent decision"
        raise UnsafeInputError(msg)
    paths = {f["filename"] for f in context["files"]}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"text", "source_paths"}:
            msg = "Invalid entry schema"
            raise UnsafeInputError(msg)
        text = entry["text"]
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_ENTRY_CHARS:
            msg = "Invalid entry length"
            raise UnsafeInputError(msg)
        # All formatting is performed by code. No links supplied by model.
        if any(c in text for c in "\n\r<>[]`\\") or re.search(r"https?://", text):
            msg = "Unsafe Markdown"
            raise UnsafeInputError(msg)
        sources = entry["source_paths"]
        if (
            not isinstance(sources, list)
            or not sources
            or not all(isinstance(p, str) and p in paths for p in sources)
        ):
            msg = "Unsubstantiated entry"
            raise UnsafeInputError(msg)
    return cast("Decision", raw)


def render(updates: str, entries: Sequence[RenderedEntry], timestamp: str) -> str:
    """Insert freshly rendered entries below the updates front matter."""
    if not updates.startswith("---\n"):
        msg = "Missing front matter"
        raise UnsafeInputError(msg)
    end = updates.find("\n---\n", 4)
    if end == -1:
        msg = "Unterminated front matter"
        raise UnsafeInputError(msg)
    stamp = dt.datetime.fromisoformat(timestamp)
    if stamp.tzinfo is None:
        msg = "Timestamp must include timezone"
        raise UnsafeInputError(msg)
    display_stamp = stamp.astimezone(dt.timezone(dt.timedelta(hours=3))).strftime(
        "%Y-%m-%d %H:%M"
    )
    lines = [f"- [ ] *\\[{display_stamp}\\]* {e['text']}" for e in entries]
    # Prevent exact duplicate descriptions, including manually added ones.
    existing = {
        re.sub(r"^- \[[ x]\] \*\\\[.*?\\\]\*\s*", "", line).strip()
        for line in updates.splitlines()
    }
    lines = [
        line
        for line, entry in zip(lines, entries, strict=True)
        if entry["text"].strip() not in existing
    ]
    if not lines:
        return updates
    offset = end + len("\n---\n")
    return updates[:offset] + "\n".join(lines) + "\n" + updates[offset:]
