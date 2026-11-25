"""Decide when a bot push should refresh the public wiki page."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

SPEC = "openapi.yaml"
PAGE = "wiki/content/platform/socrat-bot.md"
MAX_PAGE_CHARS = 200_000
MARKER = "<!-- wiki-openapi-refresh -->"
SHA = re.compile(r"[a-f0-9]{40}")


class UnsafeInputError(Exception):
    """Exception raised on unsafe wiki OpenAPI input."""


def require_sha(value: object) -> str:
    """Accept only a full 40-hex commit SHA."""
    if not isinstance(value, str) or not SHA.fullmatch(value):
        msg = "Full SHA required"
        raise UnsafeInputError(msg)
    return value


def spec_changed(event: object, files: Iterable[object] | None) -> bool:
    """Files is the GitHub compare/commit file list. Push payload is not trusted for this."""
    if not isinstance(event, dict) or event.get("ref") != "refs/heads/main":
        return False
    require_sha(event.get("after", ""))
    before = event.get("before", "")
    if before != "0" * 40:
        require_sha(before)
    return any(isinstance(item, dict) and item.get("filename") == SPEC for item in files or [])


def branch_for(sha: object) -> str:
    """Return the deterministic automation branch name for a commit."""
    return "automation/wiki-openapi-" + require_sha(sha)


def page_ok(markdown: object) -> str:
    """Verify the rendered page survived the round trip intact."""
    if not isinstance(markdown, str) or len(markdown) > MAX_PAGE_CHARS:
        msg = "Rendered page is missing or too large"
        raise UnsafeInputError(msg)
    if not markdown.startswith("---\n") or 'title: "Socrat Bot"' not in markdown.split("---", 2)[1]:
        msg = "Rendered page lost its Socrat Bot front matter"
        raise UnsafeInputError(msg)
    if "POST /v1/messages" not in markdown:
        msg = "Rendered page has no message API"
        raise UnsafeInputError(msg)
    return markdown


def select_closable(
    decision: object,
    candidates: Sequence[Mapping[str, object]],
    keep: object,
) -> list[int]:
    """Model may only name already-filtered automation PRs, never the survivor."""
    if not isinstance(decision, dict) or not isinstance(decision.get("close"), list):
        msg = "Model close list is missing"
        raise UnsafeInputError(msg)
    allowed = {item["number"] for item in candidates}
    chosen = []
    for number in decision["close"]:
        if (
            not isinstance(number, int)
            or number == keep
            or number not in allowed
            or number in chosen
        ):
            continue
        chosen.append(number)
    return chosen
